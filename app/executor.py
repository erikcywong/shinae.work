"""Workers: the Executor side of the two-layer architecture.

A Worker is an independent session with a directory of its own, a tool set
bounded by the Ticket's Mandate scope, and no authority to create Tickets.
Two planners share one tool surface:

* `mock`  — deterministic, offline, used for demos and CI;
* `live`  — DeepSeek chat-completions with the same tool schemas.

Either way the Worker ends by calling `report`, which is the only way a Ticket
learns what happened.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import carbon
import ledger
from store import Store, dumps, loads, utcnow

DEEPSEEK_URL = os.environ.get("DSH_LLM_URL", "https://api.deepseek.com/chat/completions")
DEFAULT_MODEL = os.environ.get("DSH_LLM_MODEL", "deepseek-chat")


def _cutoff(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def subject_of(thread_key: str) -> str:
    """`aero/cabin-A1` -> `A1`, `field/batch-B-2026-11` -> `B-2026-11`."""
    tail = thread_key.rsplit("/", 1)[-1]
    for prefix in ("cabin-", "batch-", "region-", "inbox"):
        if tail.startswith(prefix) and len(tail) > len(prefix):
            return tail[len(prefix):]
    return tail


class ToolError(Exception):
    pass


class ModelError(RuntimeError):
    """A model call failed for a reason a person can fix (key, balance, rate limit)."""


class ToolBox:
    """The Worker's hands. Every call is checked against the Mandate scope."""

    def __init__(self, engine, store: Store, ticket: dict, assignment_id: str, tdir: str,
                 tracer=None):
        self.engine = engine
        self.store = store
        self.ticket = ticket
        self.assignment_id = assignment_id
        self.tdir = tdir
        self.scope = set(ticket.get("scope") or [])
        self.reported = False
        self.tracer = tracer

    # -- scope ------------------------------------------------------------
    def _check(self, tool: str) -> None:
        if tool == "report":
            return
        if self.scope and tool not in self.scope:
            raise ToolError(f"tool {tool!r} is outside this Mandate scope {sorted(self.scope)}")

    def _path(self, name: str) -> str:
        safe = os.path.basename(name).replace("..", "_") or "artifact.txt"
        return os.path.join(self.tdir, safe)

    # -- tools ------------------------------------------------------------
    def telemetry_read(self, cabin: str | None = None, hours: float = 24) -> dict:
        self._check("telemetry.read")
        cabin = cabin or subject_of(self.ticket["thread_key"])
        rows = self.store.q(
            "SELECT * FROM reading WHERE cabin=? AND at>=? ORDER BY at", (cabin, _cutoff(hours))
        )
        if not rows:
            rows = list(reversed(self.store.q(
                "SELECT * FROM reading WHERE cabin=? ORDER BY at DESC LIMIT 24", (cabin,))))
        if not rows:
            raise ToolError(f"no telemetry for cabin {cabin}")

        def stat(k):
            vals = [float(r[k]) for r in rows]
            return {"min": round(min(vals), 3), "max": round(max(vals), 3),
                    "mean": round(sum(vals) / len(vals), 3),
                    "last": round(vals[-1], 3), "first": round(vals[0], 3)}

        return {
            "cabin": cabin,
            "hours": hours,
            "n": len(rows),
            "window": {"from": rows[0]["at"], "to": rows[-1]["at"]},
            "ec": stat("ec"),
            "ph": stat("ph"),
            "water_l": {"total": round(sum(float(r["water_l"]) for r in rows), 2)},
            "energy_kwh": {"total": round(sum(float(r["energy_kwh"]) for r in rows), 3)},
            "temp_c": stat("temp_c"),
            "rh": stat("rh"),
            "ppfd": stat("ppfd"),
        }

    def carbon_compute(self, batch_id: str) -> dict:
        self._check("carbon.compute")
        row = self.store.q1("SELECT * FROM batch WHERE id=?", (batch_id,))
        if not row:
            raise ToolError(f"no batch {batch_id}")
        doc = carbon.compute(row)
        doc["computed_at"] = utcnow()
        with open(self._path(f"footprint-{batch_id}.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False, indent=2))
        return {k: doc[k] for k in ("batch_id", "methodology", "totals",
                                    "intensity_kgco2e_per_kg", "hash", "warnings")}

    def ledger_append(self, batch_id: str) -> dict:
        self._check("ledger.append")
        row = self.store.q1("SELECT * FROM batch WHERE id=?", (batch_id,))
        if not row:
            raise ToolError(f"no batch {batch_id}")
        doc = carbon.compute(row)
        doc["computed_at"] = utcnow()
        res = ledger.append_document(
            self.store, doc,
            note=f"ticket={self.ticket['id']} policy=v{self.ticket['policy_version']}",
        )
        return {"batch_id": batch_id, "head": res["head"], "total_kgco2e": res["total"],
                "rows": len(res["rows"]), "doc_hash": doc["hash"]}

    def dossier_render(self) -> dict:
        self._check("dossier.render")
        doc = carbon.methodology_doc()
        lines = [
            f"# Carbon methodology {doc['id']} {doc['version']}",
            "",
            f"- status: **{doc['status']}**",
            f"- boundary: {doc['boundary']}",
            f"- functional unit: {doc['functional_unit']}",
            f"- GWP set: {doc['gwp_set']}",
            f"- methodology hash: `{doc['hash']}`",
            "",
            "## Rules",
            *[f"- {r}" for r in doc["rules"]],
            "",
            "## Invalidated when",
            *[f"- {r}" for r in doc["invalidated_when"]],
            "",
            "## Factors",
            "| id | value | unit | status | source |",
            "| --- | --- | --- | --- | --- |",
        ]
        for fid, f in doc["factors"].items():
            lines.append(f"| `{fid}` | {f['value']} | {f['unit']} | {f['status']} | {f['source']} |")
        lines += ["", "## What this dossier does **not** claim", "",
                  "- no third-party verification, no accreditation, no registry issuance",
                  "- no product carbon label may cite these numbers until the factor set is certified",
                  ""]
        with open(self._path("dossier.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return {"methodology_hash": doc["hash"], "path": "dossier.md", "status": doc["status"],
                "factors": len(doc["factors"])}

    def file_write(self, name: str, content: str) -> dict:
        self._check("file.write")
        p = self._path(name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return {"path": os.path.relpath(p, self.tdir), "bytes": len(content.encode("utf-8"))}

    def report(self, state: str, summary: str, question: str | None = None) -> dict:
        if self.reported:
            raise ToolError("already reported")
        self.reported = True
        return self.engine.report(self.ticket["id"], self.assignment_id, state, summary, question)

    SPEC = [
        {"name": "telemetry.read", "description": "Aggregate IoT readings for one cabin.",
         "params": {"cabin": "str", "hours": "number"}},
        {"name": "carbon.compute", "description": "Compute footprint for one batch, write footprint-<id>.json.",
         "params": {"batch_id": "str"}},
        {"name": "ledger.append", "description": "Append a hash-chained ledger run for one batch.",
         "params": {"batch_id": "str"}},
        {"name": "dossier.render", "description": "Render the methodology dossier (version + hashes).",
         "params": {}},
        {"name": "file.write", "description": "Write an artifact into the ticket directory.",
         "params": {"name": "str", "content": "str"}},
        {"name": "report", "description": "Finish: state=progress|waiting|ready|blocked|failed|dropped.",
         "params": {"state": "str", "summary": "str", "question": "str|null"}},
    ]

    def call(self, name: str, args: dict) -> dict:
        table = {
            "telemetry.read": self.telemetry_read,
            "carbon.compute": self.carbon_compute,
            "ledger.append": self.ledger_append,
            "dossier.render": self.dossier_render,
            "file.write": self.file_write,
            "report": self.report,
        }
        if name not in table:
            raise ToolError(f"unknown tool {name}")
        try:
            result = table[name](**args)
        except Exception as exc:
            if self.tracer:
                self.tracer(name, args, None, str(exc))
            raise
        if self.tracer:
            self.tracer(name, args, result, None)
        return result


def drift_findings(stat: dict) -> list[str]:
    """Turn a telemetry window into sentences a grower can act on."""
    out = []
    ec, ph = stat["ec"], stat["ph"]
    if ec["first"] and abs(ec["last"] - ec["first"]) / max(abs(ec["first"]), 1e-6) > 0.10:
        pct = (ec["last"] - ec["first"]) / max(abs(ec["first"]), 1e-6) * 100
        out.append(f"EC {ec['first']} -> {ec['last']} mS/cm ({pct:+.0f}%)" +
                   (" — salts accumulating, dilute and flush" if pct > 0 else " — uptake ahead of top-up"))
    if abs(ph["last"] - ph["first"]) > 0.3:
        out.append(f"pH {ph['first']} -> {ph['last']} — outside the 5.6-6.0 band, correct before next misting cycle")
    per_sample = stat["water_l"]["total"] / max(stat["n"], 1)
    if per_sample > 55:
        out.append(f"water draw {per_sample:.0f} L/sample — check nozzle drift and回收 loop")
    if not out:
        out.append("no drift above the policy thresholds in this window")
    return out


def probe_key(api_key: str, model: str | None = None, timeout: int = 15) -> tuple[bool, str]:
    """One-token check so a revoked key never turns every Ticket into a blocked one."""
    if not api_key:
        return False, "no key"
    url = os.environ.get("DSH_LLM_URL") or DEEPSEEK_URL
    body = json.dumps({"model": model or DEFAULT_MODEL,
                       "messages": [{"role": "user", "content": "ping"}],
                       "max_tokens": 1}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            json.loads(r.read().decode())
        return True, "ok"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:160]}"
    except Exception as exc:
        return False, repr(exc)[:160]


class MockPlanner:
    """Deterministic plan derived from the Ticket. Same tool surface as the live model."""

    def __init__(self, engine=None):
        self.engine = engine

    def steps(self, box: ToolBox, ticket: dict) -> list[tuple[str, dict]]:
        kind = ticket["kind"]
        inputs = box.store.q("SELECT * FROM input WHERE ticket_id=? ORDER BY at", (ticket["id"],))
        text = " ".join([ticket["title"]] + [i["text"] for i in inputs]).lower()
        latest = box.store.q1("SELECT id FROM batch ORDER BY harvest_at DESC LIMIT 1")
        batch_id = (latest or {}).get("id")
        thread_batch = subject_of(ticket["thread_key"])
        if box.store.q1("SELECT id FROM batch WHERE id=?", (thread_batch,)):
            batch_id = thread_batch

        if kind == "harvest.recorded" or "batch" in text or "批次" in text:
            return [("carbon.compute", {"batch_id": batch_id}),
                    ("ledger.append", {"batch_id": batch_id}),
                    ("dossier.render", {})]
        if kind == "factor.updated":
            return [("carbon.compute", {"batch_id": batch_id}),
                    ("ledger.append", {"batch_id": batch_id})]
        if kind == "human.message":
            # a person's question is answered from the dossier first, then the latest batch
            return [("dossier.render", {}), ("carbon.compute", {"batch_id": batch_id})]
        if kind == "brand.question":
            return [("dossier.render", {})]
        cabin = subject_of(ticket["thread_key"])
        return [("telemetry.read", {"cabin": cabin, "hours": 24})]


class LivePlanner:
    """Tool-calling loop against a DeepSeek-compatible chat endpoint."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model

    def _request(self, messages, tools) -> dict:
        body = json.dumps({"model": self.model, "messages": messages, "tools": tools,
                           "tool_choice": "auto", "temperature": 0.2}).encode("utf-8")
        url = os.environ.get("DSH_LLM_URL") or DEEPSEEK_URL
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")[:300]
            hint = {401: "API key 无效或已吊销：到 platform 重新创建，写进 var/llm.env",
                    402: "余额不足：充值后再试",
                    429: "触发限流：稍后重试或降低频率",
                    404: "端点或模型名不对：检查 DSH_LLM_URL / DSH_LLM_MODEL"}.get(exc.code, "检查模型端点")
            raise ModelError(f"HTTP {exc.code} · {hint} · {raw}") from None
        except urllib.error.URLError as exc:
            raise ModelError(f"网络不可达：{exc.reason}") from None

    def tools_payload(self, box: ToolBox) -> list[dict]:
        out = []
        for spec in ToolBox.SPEC:
            if spec["name"] != "report" and box.scope and spec["name"] not in box.scope:
                continue
            props = {k: ({"type": "number"} if v == "number" else {"type": "string"})
                     for k, v in spec["params"].items()}
            out.append({"type": "function", "function": {
                "name": spec["name"].replace(".", "_"), "description": spec["description"],
                "parameters": {"type": "object", "properties": props, "required": list(props)}}})
        return out

    def run(self, box: ToolBox, ticket: dict, max_steps: int = 12) -> str:
        mandate = ticket["mandate"]
        cabins = [r["cabin"] for r in box.store.q("SELECT DISTINCT cabin FROM reading LIMIT 12")]
        batches = [r["id"] for r in box.store.q("SELECT id FROM batch LIMIT 12")]
        system = (
            "You are a worker in a two-layer agent system. You hold exactly one Ticket.\n"
            f"Ticket: {ticket['title']}\nScope allowed by your Mandate: {ticket['scope']}\n"
            f"Policy v{mandate.get('policy_version')} hash {str(mandate.get('policy_hash'))[:12]}\n"
            f"Known cabins (telemetry.read takes one of these): {', '.join(cabins) or 'none'}\n"
            f"Known batches (carbon.compute / ledger.append take one of these): {', '.join(batches) or 'none'}\n"
            "A batch id is not a cabin: never ask for telemetry of a batch id.\n"
            "Rules: act only inside the scope; never invent sensor readings or factors; finish by calling report; "
            "keep the summary under 400 characters; ask one concrete question only if a person must decide."
        )
        brief = ticket["title"]
        inputs = box.store.q("SELECT text FROM input WHERE ticket_id=? AND delivered=0 ORDER BY at", (ticket["id"],))
        if inputs:
            brief += "\nInputs:\n" + "\n".join(f"- {i['text']}" for i in inputs)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": brief}]
        tools = self.tools_payload(box)
        for _ in range(max_steps):
            resp = self._request(messages, tools)
            msg = resp["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            messages.append(msg)
            if not calls:
                if box.reported:
                    return "reported"
                return (msg.get("content") or "no tool call")[:400]
            for call in calls:
                name = call["function"]["name"].replace("_", ".")
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                    result = box.call(name, args)
                    content = dumps(result)[:4000]
                except Exception as exc:  # a refused tool is a fact, not a crash
                    content = f"ERROR: {exc}"
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
                if box.reported:
                    return "reported"
        return "max_steps"


class Worker:
    def __init__(self, engine, store: Store, var_dir: str, mode: str = "mock",
                 api_key: str | None = None, bus=None, step_delay: float = 0.45):
        self.engine = engine
        self.store = store
        self.var_dir = var_dir
        self.mode = mode
        self.api_key = api_key
        self.bus = bus or (lambda t, p: None)
        self.step_delay = step_delay

    def launch(self, ticket_id: str, assignment_id: str) -> None:
        threading.Thread(target=self._run, args=(ticket_id, assignment_id), daemon=True,
                         name=f"worker-{ticket_id[-6:]}").start()

    def _emit(self, ticket_id: str, tool: str, args: dict, result=None, error: str | None = None) -> None:
        self.engine.emit(
            "worker.step", ticket_id,
            {"tool": tool, "args": {k: str(v)[:120] for k, v in (args or {}).items()},
             "summary": self._brief(result), "error": error},
        )

    @staticmethod
    def _brief(result) -> str:
        if isinstance(result, dict):
            if "totals" in result:
                return f"total {result['totals']['total']} kgCO2e, {result['intensity_kgco2e_per_kg']}/kg"
            if "head" in result:
                return f"ledger head {result['head'][:16]}… total {result.get('total_kgco2e')}"
            if "ec" in result:
                return f"EC {result['ec']['min']}-{result['ec']['max']} mS/cm, n={result['n']}"
            if "path" in result:
                return f"wrote {result['path']}"
            if "state" in result:
                return f"report {result['state']}"
        return str(result)[:160]

    def _compose_summary(self, ticket: dict, results: dict) -> str:
        parts = []
        tel = results.get("telemetry.read")
        if tel:
            parts.append(f"Cabin {tel['cabin']} ({tel['n']} samples, {tel['window']['from'][:16]}→{tel['window']['to'][11:16]}): "
                         + "; ".join(drift_findings(tel)) + ".")
            parts.append(f"Energy {tel['energy_kwh']['total']} kWh, water {tel['water_l']['total']} L in window. "
                         "Findings written to findings.md.")
        comp = results.get("carbon.compute")
        if comp:
            parts.append(f"Batch {comp['batch_id']}: {comp['totals']['total']} kgCO2e total, "
                         f"{comp['intensity_kgco2e_per_kg']} kgCO2e/kg green "
                         f"(S1 {comp['totals']['scope1']} / S2 {comp['totals']['scope2']} / S3 {comp['totals']['scope3']}).")
        led = results.get("ledger.append")
        if led:
            parts.append(f"Ledger run appended: {led['rows']} rows, head {led['head'][:16]}….")
        dos = results.get("dossier.render")
        if dos:
            parts.append(f"Dossier rendered at methodology hash {dos['methodology_hash'][:16]}… "
                         f"(status: factors unverified).")
        if not parts:
            parts.append("No tool result to summarise.")
        text = " ".join(parts)
        return text[:600]

    def _run(self, ticket_id: str, assignment_id: str) -> None:
        ticket = self.engine.ticket(ticket_id)
        if not ticket:
            return
        asg = self.store.q1("SELECT * FROM assignment WHERE id=?", (assignment_id,))
        if not asg or asg["status"] == "ended":
            return
        self.engine.assignment_started(ticket_id, assignment_id)
        tdir = ticket["dir"]
        os.makedirs(tdir, exist_ok=True)
        tpath = os.path.join(tdir, "transcript.md")
        with open(tpath, "a", encoding="utf-8") as f:
            f.write(f"\n## attempt {asg['attempts']} — {utcnow()} — `{assignment_id}`\n"
                    f"- ticket: {ticket['title']}\n- scope: {', '.join(ticket['scope'])}\n")
        box = ToolBox(self.engine, self.store, ticket, assignment_id, tdir,
                      tracer=lambda tool, args, result, error: self._emit(ticket_id, tool, args, result, error))
        results: dict[str, dict] = {}
        try:
            if self.mode == "live" and self.api_key:
                self._emit(ticket_id, "planner", {"mode": "live", "model": DEFAULT_MODEL})
                try:
                    status = LivePlanner(self.api_key).run(box, ticket)
                except ModelError as exc:
                    # a key/balance problem is a person's decision, not a worker bug
                    self.engine.report(ticket_id, assignment_id, "blocked",
                                       f"模型调用失败：{exc}"[:500],
                                       question="把有效 key 写进 var/llm.env 后重试，或先切回 mock（去掉 --live）？")
                    return
                if not box.reported:
                    self.engine.report(ticket_id, assignment_id, "blocked",
                                       f"Live planner ended without a report ({status}).",
                                       question="Retry with a narrower scope, or stop this Ticket?")
                return
            plan = MockPlanner(self.engine).steps(box, ticket)
            for tool, args in plan:
                if box.reported:
                    break
                self.engine.heartbeat(assignment_id)
                time.sleep(self.step_delay)
                try:
                    result = box.call(tool, args)   # the tracer emits worker.step
                    results[tool] = result if isinstance(result, dict) else {}
                    with open(tpath, "a", encoding="utf-8") as f:
                        f.write(f"- `{tool}` {json.dumps(args, ensure_ascii=False)} → {self._brief(result)}\n")
                except ToolError as exc:
                    with open(tpath, "a", encoding="utf-8") as f:
                        f.write(f"- `{tool}` REFUSED: {exc}\n")
            if not box.reported:
                if not results:
                    box.report("blocked",
                               "No tool in this plan produced a result; nothing was measured, so nothing is claimed.",
                               question="Widen the scope or fix the plan for this Ticket?")
                    with open(tpath, "a", encoding="utf-8") as f:
                        f.write(f"- blocked: empty result set\n")
                    return
                summary = self._compose_summary(ticket, results)
                if "telemetry.read" in results:
                    tel = results["telemetry.read"]
                    findings = "\n".join(f"- {x}" for x in drift_findings(tel))
                    try:
                        box.file_write("findings.md",
                                       f"# Cabin {tel['cabin']} — 24h diagnosis\n\n{findings}\n\n"
                                       f"Window: {tel['window']['from']} → {tel['window']['to']}, n={tel['n']}\n"
                                       f"Energy: {tel['energy_kwh']['total']} kWh · Water: {tel['water_l']['total']} L\n")
                    except ToolError:
                        pass
                box.report("ready", summary)
            with open(tpath, "a", encoding="utf-8") as f:
                f.write(f"- finished {utcnow()}\n")
        except Exception as exc:  # a worker crash must surface as a Report, never as silence
            self._emit(ticket_id, "worker", {}, error=repr(exc))
            try:
                self.engine.report(ticket_id, assignment_id, "failed",
                                   f"Worker crashed: {exc!r}"[:400],
                                   question="Retry this Ticket, or stop it and take over by hand?")
            except Exception:
                pass
