"""Composition root: wires the kernel, workers, the simulator and the effect queue.

Kept deliberately thin — no domain rules here, only construction, background
loops and the read models the panel consumes.  Mirrors `Runtime` in
dsh-superagent/src/app/runtime.ts, including the restart path: pending work is
re-launched, interrupted work is re-queued with a recovery note.
"""
from __future__ import annotations

import os
import queue
import threading
import time
from datetime import datetime, timezone

import carbon
import ledger
from engine import Engine
from executor import Worker
from feishu import FeishuBridge, FeishuClient, FeishuConfig
from policy import Policy
from sim import Sim
from store import Store, loads, utcnow

APP_VERSION = "0.1.0"


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class Runtime:
    def __init__(self, var_dir: str | None = None, mode: str | None = None,
                 sim_interval: float | None = None, step_delay: float | None = None):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.root = root
        self.var_dir = var_dir or os.path.join(root, "var")
        os.makedirs(self.var_dir, exist_ok=True)
        self.store = Store(os.path.join(self.var_dir, "state.db"))
        self.policy = Policy(self.store)
        self._subs: set[queue.Queue] = set()
        self._subs_lock = threading.Lock()
        self.engine = Engine(self.store, self.policy, self.var_dir, bus=self._publish)
        self.api_key = os.environ.get("DEEPSEEK_API_KEY") or None
        # Explicit, never inferred: a stale key in var/llm.env must not silently switch
        # the whole system to a model that answers 401. `--live` is the only switch.
        self.mode = mode or "mock"
        self.worker = Worker(self.engine, self.store, self.var_dir, mode=self.mode,
                             api_key=self.api_key, bus=self._publish,
                             step_delay=float(step_delay if step_delay is not None else 0.45))
        self.sim = Sim(self.store, self.engine,
                       interval_s=float(sim_interval if sim_interval is not None else 12))
        self.feishu = FeishuBridge(self)
        self.started_at = time.time()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.health = {"passes": 0, "last_pass_at": None, "effects_done": 0, "effects_failed": 0,
                       "watchdog_interrupts": 0, "last_watchdog_at": None, "sim_ticks": 0,
                       "errors": []}

    # ------------------------------------------------------------ publish
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._subs_lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._subs_lock:
            self._subs.discard(q)

    def _publish(self, topic: str, payload) -> None:
        with self._subs_lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait({"topic": topic, "payload": payload})
            except queue.Full:
                pass
        bridge = getattr(self, "feishu", None)
        if bridge and topic == "event" and isinstance(payload, dict):
            try:
                bridge.on_engine_event(payload.get("kind", ""), payload.get("data") or {})
            except Exception as exc:  # a bridge bug must not break the kernel
                self._record_error(f"feishu bridge: {exc!r}")

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._seed()
        self._resume_after_restart()
        self.feishu.start()
        for name, fn, period in (("passes", self._passes_loop, 0.8),
                                 ("effects", self._effects_loop, 0.4),
                                 ("watchdog", self._watchdog_loop, 2.0),
                                 ("sim", self._sim_loop, None)):
            t = threading.Thread(target=fn, args=() if period is None else (period,),
                                 daemon=True, name=f"rt-{name}")
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self.feishu.stop()
        for t in self._threads:
            t.join(timeout=2)

    # ------------------------------------------------------------ seeds
    def _seed(self) -> None:
        if not self.store.q1("SELECT id FROM batch LIMIT 1"):
            batches = [
                ("B-2026-11", "Batch 2026-11 (Cabin A1)", "A1", 41.5, "2026-11-18T02:10:00Z",
                 2180.0, 3720.0, 18.4, 0.0, 118.0, "CN",
                 "aeroponic cycle, zero substrate; 6-week topping harvest"),
                ("B-2026-10", "Batch 2026-10 (Cabin B2)", "B2", 38.2, "2026-10-21T03:40:00Z",
                 2040.0, 3410.0, 17.1, 0.0, 96.0, "CN",
                 "aeroponic cycle; nutrient A/B split, 2 EC steps"),
                ("B-2026-09", "Batch 2026-09 (Cabin C3, SG trial)", "C3", 12.6, "2026-09-12T01:20:00Z",
                 690.0, 1180.0, 5.8, 0.0, 210.0, "SG",
                 "Singapore trial row; freight-adjusted"),
            ]
            with self.store.tx() as c:
                for b in batches:
                    c.execute(
                        "INSERT INTO batch(id,name,cabin,kg_green,harvest_at,kwh,water_l,nutrient_kg,"
                        "substrate_kg,freight_tkm,region,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", b)
        self.sim.seed_history(6, 10)

    def _resume_after_restart(self) -> None:
        for a in self.store.q("SELECT * FROM assignment WHERE status='pending'"):
            self.engine.enqueue("launch", a["ticket_id"],
                                {"ticket_id": a["ticket_id"], "assignment_id": a["id"]})
        for a in self.store.q("SELECT * FROM assignment WHERE status='running'"):
            self.engine.interrupt(a, float(self.policy.doc["watchdog_stale_s"]))
            self.health["watchdog_interrupts"] += 1

    # ------------------------------------------------------------ loops
    def _passes_loop(self, period: float) -> None:
        while not self._stop.wait(period):
            try:
                self.engine.passes()
                self.health["passes"] += 1
                self.health["last_pass_at"] = utcnow()
            except Exception as exc:  # a loop that dies silently is the worst failure mode
                self._record_error(f"passes: {exc!r}")

    def _effects_loop(self, period: float) -> None:
        while not self._stop.wait(period):
            try:
                self._effects_once()
            except Exception as exc:
                self._record_error(f"effects: {exc!r}")

    def _effects_once(self) -> None:
        rows = self.store.q(
            "SELECT * FROM effect WHERE status='pending' AND due_at<=? ORDER BY id LIMIT 20", (utcnow(),))
        for r in rows:
            payload = loads(r["payload"], {})
            try:
                if r["kind"] == "launch":
                    self.worker.launch(payload["ticket_id"], payload["assignment_id"])
                elif r["kind"] == "reply":
                    self._deliver_reply(payload["reply_id"])
                with self.store.tx() as c:
                    c.execute("UPDATE effect SET status='done' WHERE id=?", (r["id"],))
                self.health["effects_done"] += 1
            except Exception as exc:
                attempts = int(r["attempts"]) + 1
                delay = min(60, 2 ** attempts)
                from datetime import timedelta
                due = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(
                    timespec="seconds").replace("+00:00", "Z")
                with self.store.tx() as c:
                    c.execute("UPDATE effect SET attempts=?, last_error=?, due_at=? WHERE id=?",
                              (attempts, repr(exc)[:300], due, r["id"]))
                self.health["effects_failed"] += 1
                self._record_error(f"effect {r['kind']}: {exc!r}")

    def _deliver_reply(self, reply_id: str) -> None:
        row = self.store.q1("SELECT * FROM outbox WHERE id=?", (reply_id,))
        if not row or row["status"] != "pending":
            return
        with self.store.tx() as c:
            c.execute("UPDATE outbox SET status='sent' WHERE id=?", (reply_id,))
        self._publish("reply", {"id": reply_id, "channel": row["channel"],
                                "ticket_id": row["ticket_id"], "body": loads(row["body"], {})})

    def _watchdog_loop(self, period: float) -> None:
        while not self._stop.wait(period):
            try:
                stale = float(self.policy.doc["watchdog_stale_s"])
                now = datetime.now(timezone.utc)
                for a in self.engine.running_assignments():
                    age = (now - _parse(a["heartbeat_at"])).total_seconds()
                    if age > stale:
                        self.engine.interrupt(a, stale)
                        self.health["watchdog_interrupts"] += 1
                self.health["last_watchdog_at"] = utcnow()
            except Exception as exc:
                self._record_error(f"watchdog: {exc!r}")

    def _sim_loop(self) -> None:
        interval = max(3.0, self.sim.interval_s)
        while not self._stop.wait(interval):
            try:
                if not self.policy.doc["paused"]:
                    self.sim.tick()
                    self.health["sim_ticks"] += 1
            except Exception as exc:
                self._record_error(f"sim: {exc!r}")

    def _record_error(self, msg: str) -> None:
        self.health["errors"] = (self.health["errors"] + [{"at": utcnow(), "error": msg}])[-8:]

    # ------------------------------------------------------------ actions
    def human_message(self, text: str) -> dict:
        return self.engine.intake(source="brand", thread_key="brand/inbox", kind="human.message",
                                  text=text, actor="erik", severity="info",
                                  payload={"topic": text[:60]}, thread_label="Brand inbox")

    def inject_anomaly(self, cabin: str = "A1") -> dict:
        readings = self.sim.tick(anomaly=cabin)
        return {"cabin": cabin, "readings": [r for r in readings if r["cabin"] == cabin]}

    def record_harvest(self, batch_id: str | None = None) -> dict:
        b = (self.store.q1("SELECT * FROM batch WHERE id=?", (batch_id,)) if batch_id
             else self.store.q1("SELECT * FROM batch ORDER BY harvest_at DESC LIMIT 1"))
        if not b:
            raise ValueError("no batch")
        return self.engine.intake(source="field", thread_key=f"field/batch-{b['id']}",
                                  kind="harvest.recorded", text=f"Harvest of {b['kg_green']} kg green recorded",
                                  actor="field.log", severity="info",
                                  payload={"batch": b["id"], "kg_green": b["kg_green"]},
                                  thread_label=f"Batch {b['id']}")

    def factor_update(self, region: str = "CN") -> dict:
        return self.engine.intake(source="carbon", thread_key=f"carbon/region-{region}",
                                  kind="factor.updated",
                                  text=f"Grid factor for {region} updated by the registry feed",
                                  actor="registry.feed", severity="info",
                                  payload={"region": region}, thread_label=f"Carbon region {region}")

    def set_policy(self, patch: dict) -> dict:
        row = self.policy.bump(patch)
        n = self.engine.policy_changed()
        return {"version": row["version"], "hash": row["hash"], "notified_tickets": n}

    def dossier_text(self) -> str:
        """One-screen methodology summary for chat commands. Says what it cannot claim."""
        d = carbon.methodology_doc()
        factors = ", ".join(f"{k}={v['value']}{v['unit']}({v['status']})" for k, v in d["factors"].items())
        return (f"{d['id']} {d['version']} · hash {d['hash'][:16]}…\n"
                f"边界: {d['boundary']} · 功能单位: {d['functional_unit']}\n"
                f"因子: {factors}\n"
                f"状态: {d['status']} — 未经第三方核证，不可用于对外碳标签。")

    def recompute(self, batch_id: str) -> dict:
        b = self.store.q1("SELECT * FROM batch WHERE id=?", (batch_id,))
        if not b:
            raise ValueError("no batch")
        doc = carbon.compute(b)
        doc["computed_at"] = utcnow()
        res = ledger.append_document(self.store, doc, note="manual recompute from the panel", kind="revision")
        return {"batch_id": batch_id, "head": res["head"], "total": res["total"]}

    def reload_secrets(self) -> dict:
        """Re-read var/*.env without a restart: rotate a model key or a Feishu secret in place."""
        loaded = 0
        for rel in (".env", os.path.join("var", "llm.env"), os.path.join("var", "feishu.env")):
            path = os.path.join(self.root, rel)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
                    loaded += 1
        self.api_key = os.environ.get("DEEPSEEK_API_KEY") or None
        self.worker.api_key = self.api_key
        self.feishu.cfg = FeishuConfig()
        self.feishu.client = FeishuClient(self.feishu.cfg) if self.feishu.cfg.transport == "api" else None
        return {
            "ok": True,
            "variables": loaded,
            "mode": self.mode,
            "llm_key": ("…" + self.api_key[-4:]) if self.api_key else "missing",
            "feishu": self.feishu.cfg.describe(),
        }

    # ------------------------------------------------------------ read model
    def snapshot(self) -> dict:
        d = self.policy.doc
        tickets = []
        for t in self.store.q("SELECT * FROM ticket ORDER BY created_at DESC LIMIT 40"):
            t["mandate"] = loads(t["mandate"], {})
            t["scope"] = loads(t["scope"], [])
            t["latest_report"] = loads(t["latest_report"], None)
            asgs = self.store.q("SELECT * FROM assignment WHERE ticket_id=? ORDER BY heartbeat_at DESC LIMIT 3", (t["id"],))
            t["assignments"] = asgs
            t["reports"] = self.store.q("SELECT state, at FROM report WHERE ticket_id=? ORDER BY at DESC LIMIT 5", (t["id"],))
            t["inputs"] = self.store.q("SELECT kind, text, at, delivered FROM input WHERE ticket_id=? ORDER BY at", (t["id"],))
            files = []
            if os.path.isdir(t["dir"]):
                for f in sorted(os.listdir(t["dir"])):
                    p = os.path.join(t["dir"], f)
                    if os.path.isfile(p):
                        files.append({"name": f, "bytes": os.path.getsize(p)})
            t["artifacts"] = files
            t["steps"] = self.store.q(
                "SELECT at, data FROM event WHERE kind='worker.step' AND subject=? ORDER BY id DESC LIMIT 8",
                (t["id"],))
            t["steps"] = [{"at": s["at"], **loads(s["data"], {})} for s in reversed(t["steps"])]
            tickets.append(t)
        return {
            "status": {
                "app": APP_VERSION,
                "mode": self.mode,
                "llm": "live" if (self.mode == "live" and self.api_key) else "mock",
                "model": os.environ.get("DSH_LLM_MODEL", "deepseek-chat"),
                "policy_version": d["version"],
                "policy_hash": d["hash"],
                "policy_mode": d["mode"],
                "paused": d["paused"],
                "uptime_s": round(time.time() - self.started_at, 1),
                "sim": True,
                "watchdog_stale_s": d["watchdog_stale_s"],
                "var_dir": os.path.relpath(self.var_dir, self.root),
            },
            "counts": {
                "triggers": self.store.q1("SELECT COUNT(*) n FROM trigger")["n"],
                "decisions": self.store.q1("SELECT COUNT(*) n FROM decision")["n"],
                "open": self.store.q1("SELECT COUNT(*) n FROM ticket WHERE status='open'")["n"],
                "ended": self.store.q1("SELECT COUNT(*) n FROM ticket WHERE status='ended'")["n"],
                "ledger_rows": self.store.q1("SELECT COUNT(*) n FROM ledger_entry")["n"],
                "effects_pending": self.store.q1("SELECT COUNT(*) n FROM effect WHERE status='pending'")["n"],
                # a question needs a person until the Ticket itself is resolved
                "attention": sum(1 for t in tickets if t["status"] == "open" and (t["latest_report"] or {}).get("state")
                                 in ("blocked", "failed", "waiting")),
            },
            "health": self.health,
            "policy": {k: v for k, v in d.items() if k in ("version", "hash", "paused", "mode",
                                                           "eval_timeout_s", "watchdog_stale_s", "sources")},
            "rules": d["rules"],
            "cabins": self.sim.cabins(),
            "threads": self.store.q("SELECT * FROM thread ORDER BY updated_at DESC LIMIT 20"),
            "tickets": tickets,
            "triggers": [dict(r, payload=loads(r["payload"], {})) for r in
                         self.store.q("SELECT * FROM trigger ORDER BY at DESC LIMIT 40")],
            "decisions": self.store.q("SELECT * FROM decision ORDER BY at DESC LIMIT 25"),
            "events": [dict(e, data=loads(e["data"], {})) for e in
                       self.store.q("SELECT * FROM event ORDER BY id DESC LIMIT 80")],
            "ledger": ledger.summary(self.store),
            "ledger_verify": ledger.verify(self.store),
            "dossier": {k: v for k, v in carbon.methodology_doc().items() if k != "factors"},
            "factors": carbon.FACTORS,
            "outbox": [dict(o, body=loads(o["body"], {})) for o in
                       self.store.q("SELECT * FROM outbox ORDER BY at DESC LIMIT 15")],
            "feishu": self.feishu.snapshot(),
        }
