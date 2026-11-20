"""Live-planner test against a local OpenAI-style stub — proves the live path
without spending a token or needing a real key.

    python tests/live_smoke.py

The stub answers the first tool-calling turn with `telemetry.read`, the second
with `report(ready, ...)`. If the Worker's live loop, tool mapping and report
plumbing work, the Ticket ends `ready` with the model's summary.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

STUB_PORT = 8899
os.environ["DSH_LLM_URL"] = f"http://127.0.0.1:{STUB_PORT}/chat/completions"
os.environ["DSH_LLM_MODEL"] = "stub-model"
os.environ["DEEPSEEK_API_KEY"] = "sk-stub-not-a-real-key"

CALLS = {"n": 0}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path.startswith("/unauthorized"):
            raw = b'{"error":{"message":"Authentication Fails","type":"authentication_error"}}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        CALLS["n"] += 1
        turn = CALLS["n"]
        if turn == 1:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "telemetry_read",
                             "arguments": json.dumps({"cabin": "A1", "hours": 24})}}]}
        elif turn == 2:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_2", "type": "function",
                "function": {"name": "report",
                             "arguments": json.dumps({"state": "ready",
                                                      "summary": "model says: EC drift confirmed; dossier rendered."})}}]}
        else:
            msg = {"role": "assistant", "content": "done"}
        payload = {"choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls"}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    httpd = ThreadingHTTPServer(("127.0.0.1", STUB_PORT), Stub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    from runtime import Runtime  # imported after DSH_LLM_URL is set

    var = os.path.join(ROOT, "var", f"live-{os.getpid()}")
    rt = Runtime(var_dir=var, mode="live", sim_interval=10_000, step_delay=0.01)
    rt.start()
    fails = []
    try:
        if rt.mode != "live" or not rt.worker.api_key:
            fails.append("runtime did not enter live mode")
        rt.inject_anomaly("A1")
        deadline = time.time() + 20
        ticket = {}
        while time.time() < deadline and not ticket:
            found = rt.store.q("SELECT * FROM ticket WHERE kind='iot.anomaly'")
            ticket = found[0] if found else {}
            time.sleep(0.1)
        if not ticket:
            fails.append("no ticket created")
        else:
            t0 = time.time()
            while time.time() - t0 < 25:
                t = rt.engine.ticket(ticket["id"])
                if t and t["status"] == "ended":
                    break
                time.sleep(0.1)
            t = rt.engine.ticket(ticket["id"]) or {}
            rep = t.get("latest_report") or {}
            if t.get("status") != "ended":
                fails.append(f"ticket did not end (status={t.get('status')})")
            if "model says" not in (rep.get("summary") or ""):
                fails.append(f"summary did not come from the model: {rep.get('summary')!r}")
            steps = rt.store.q("SELECT data FROM event WHERE kind='worker.step' AND subject=?",
                               (ticket["id"],))
            if not any("live" in (s["data"] or "") for s in steps):
                fails.append("no live planner step recorded")
            if CALLS["n"] < 2:
                fails.append(f"stub was called {CALLS['n']} times, expected >= 2")

        # phase 2: a revoked key must become a `blocked` report with a fix hint, not a crash
        os.environ["DSH_LLM_URL"] = f"http://127.0.0.1:{STUB_PORT}/unauthorized"
        rt.inject_anomaly("B2")
        deadline = time.time() + 20
        t2 = {}
        while time.time() < deadline and not t2:
            found = rt.store.q("SELECT * FROM ticket WHERE kind='iot.anomaly' AND thread_key='aero/cabin-B2'")
            t2 = found[0] if found else {}
            time.sleep(0.1)
        if not t2:
            fails.append("no ticket for the 401 phase")
        else:
            t0 = time.time()
            while time.time() - t0 < 20:
                t = rt.engine.ticket(t2["id"])
                if t and (t["latest_report"] or {}).get("state") in ("blocked", "failed"):
                    break
                time.sleep(0.1)
            t = rt.engine.ticket(t2["id"]) or {}
            rep = t.get("latest_report") or {}
            if rep.get("state") != "blocked":
                fails.append(f"401 phase should report blocked, got {rep.get('state')}")
            if "401" not in (rep.get("summary") or ""):
                fails.append(f"401 hint missing from summary: {rep.get('summary')!r}")
            if not rep.get("question"):
                fails.append("blocked report should carry one question for a person")
    finally:
        rt.stop()
        httpd.shutdown()

    print("stub calls:", CALLS["n"])
    if fails:
        for f in fails:
            print("[FAIL]", f)
        return 1
    print("[ok] live planner drove the worker, called tools, and reported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
