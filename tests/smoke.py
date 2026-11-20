"""End-to-end smoke test: no HTTP, no browser, real kernel.

    python tests/smoke.py

Uses a throw-away state directory, drives the full Super-agent flow, and exits
non-zero on the first broken invariant.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import carbon  # noqa: E402
import ledger  # noqa: E402
from runtime import Runtime  # noqa: E402

OK, FAIL = "[ok]", "[FAIL]"
fails: list[str] = []


def check(cond, msg):
    print(f"{OK if cond else FAIL} {msg}")
    if not cond:
        fails.append(msg)


def wait_ready(rt: Runtime, ticket_id: str, timeout: float = 20.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = rt.engine.ticket(ticket_id)
        if t and t["status"] == "ended":
            return t
        time.sleep(0.15)
    return rt.engine.ticket(ticket_id) or {}


def main() -> int:
    var = os.path.join(ROOT, "var", f"smoke-{os.getpid()}-{int(time.time())}")
    os.makedirs(var, exist_ok=True)
    rt = Runtime(var_dir=var, mode="mock", sim_interval=10_000, step_delay=0.3)
    rt.start()
    try:
        # 1. sensor anomaly -> trigger -> eval -> ticket -> worker -> report
        rt.inject_anomaly("A1")
        deadline = time.time() + 10
        ticket = {}
        while time.time() < deadline and not ticket:
            found = rt.store.q("SELECT * FROM ticket WHERE kind='iot.anomaly'")
            if found:
                ticket = found[0]
            time.sleep(0.1)
        check(bool(ticket), "iot anomaly produced a Ticket")
        if ticket:
            t = wait_ready(rt, ticket["id"])
            check(t.get("status") == "ended", "anomaly Ticket ended")
            rep = t.get("latest_report") or {}
            check(rep.get("state") == "ready", f"report state ready (got {rep.get('state')})")
            check("Cabin A1" in (rep.get("summary") or ""), "report names the cabin")
            files = os.listdir(t["dir"]) if os.path.isdir(t["dir"]) else []
            check("findings.md" in files, f"findings.md written (dir: {files})")
            check(any(f.startswith("transcript") for f in files), "transcript written")
            m = t.get("mandate") or {}
            check(m.get("policy_version") == 1, "mandate records policy version")

        # 2. duplicate anomaly on the same thread fans out instead of a new Ticket
        rt.inject_anomaly("B2")
        deadline = time.time() + 10
        while time.time() < deadline and not rt.store.q(
                "SELECT id FROM ticket WHERE thread_key='aero/cabin-B2' AND status='open'"):
            time.sleep(0.05)
        rt.inject_anomaly("B2")
        time.sleep(0.6)
        n_open = rt.store.q("SELECT COUNT(*) n FROM ticket WHERE thread_key='aero/cabin-B2'")[0]["n"]
        check(n_open == 1, f"second anomaly fanned out to the live Ticket (tickets on thread: {n_open})")
        check(rt.store.q("SELECT COUNT(*) n FROM input WHERE ticket_id IN "
                         "(SELECT id FROM ticket WHERE thread_key='aero/cabin-B2')")[0]["n"] >= 1,
              "fan-out recorded an Input")

        # 3. harvest -> carbon -> ledger -> chain verifies
        rt.record_harvest("B-2026-11")
        time.sleep(1.5)
        ht = rt.store.q("SELECT * FROM ticket WHERE kind='harvest.recorded' ORDER BY created_at DESC LIMIT 1")
        check(bool(ht), "harvest produced a Ticket")
        if ht:
            t = wait_ready(rt, ht[0]["id"], timeout=30)
            check(t.get("status") == "ended", "harvest Ticket ended")
            rep = t.get("latest_report") or {}
            check("kgCO2e" in (rep.get("summary") or ""), "report quotes kgCO2e")
            rows = rt.store.q("SELECT COUNT(*) n FROM ledger_entry WHERE batch_id='B-2026-11'")[0]["n"]
            check(rows >= 6, f"ledger rows appended ({rows})")
            v = ledger.verify(rt.store, "B-2026-11")
            check(v["ok"], f"ledger chain verifies ({v})")
            # tamper detection
            with rt.store.tx() as c:
                c.execute("UPDATE ledger_entry SET kgco2e=kgco2e+1 WHERE batch_id='B-2026-11' AND id=("
                          "SELECT MIN(id) FROM ledger_entry WHERE batch_id='B-2026-11')")
            check(not ledger.verify(rt.store, "B-2026-11")["ok"], "tampering breaks the chain")

        # 4. human message -> addressed Ticket
        rt.human_message("给我 B-2026-11 的碳账本与方法学摘要")
        time.sleep(1.5)
        hm = rt.store.q("SELECT * FROM ticket WHERE kind='human.message' ORDER BY created_at DESC LIMIT 1")
        check(bool(hm), "human message produced a Ticket")
        if hm:
            t = wait_ready(rt, hm[0]["id"], timeout=20)
            check(t.get("status") == "ended", "human Ticket ended")
            mand = t.get("mandate") or {}
            check(mand.get("via") == "addressed", "mandate via=addressed")

        # 5. record mode: proactive work is recorded, not executed
        rt.set_policy({"mode": "record"})
        rt.engine.intake(source="brand", thread_key="brand/inbox", kind="brand.question",
                         text="Can you explain the water footprint?", actor="brand.inbox",
                         payload={"topic": "water"}, thread_label="Brand inbox")
        time.sleep(1.2)
        dec = rt.store.q("SELECT * FROM decision ORDER BY at DESC LIMIT 1")
        check(bool(dec) and dec[0]["reason"] in ("would_accept", "duplicate_open_ticket"),
              f"record mode did not create proactive work (reason={dec[0]['reason'] if dec else None})")

        # 6. pause: no Eval while paused
        rt.set_policy({"paused": True, "mode": "auto"})
        before = rt.store.q("SELECT COUNT(*) n FROM ticket")[0]["n"]
        rt.inject_anomaly("C3")
        time.sleep(1.5)
        after = rt.store.q("SELECT COUNT(*) n FROM ticket")[0]["n"]
        check(before == after, f"paused kernel created no Ticket ({before}->{after})")

        # 7. Feishu bridge: the same kernel, driven from chat
        rt.set_policy({"paused": False, "mode": "auto"})
        fs = rt.feishu
        r = fs.simulate("/status", chat_id="oc_test")
        check(r["status"] == 200, "feishu /status accepted")
        time.sleep(0.6)
        last = rt.store.q("SELECT * FROM feishu_out ORDER BY at DESC LIMIT 1")
        check(bool(last) and "policy v" in last[0]["body"], "feishu /status answered in the chat")
        check(last[0]["status"] in ("simulated", "sent"), f"outbound recorded ({last[0]['status']})")

        fs.simulate("告诉我 B-2026-11 的碳账本", chat_id="oc_test")
        deadline = time.time() + 10
        ftk = {}
        while time.time() < deadline and not ftk:
            found = rt.store.q("SELECT * FROM ticket WHERE thread_key='feishu/chat-oc_test'")
            ftk = found[0] if found else {}
            time.sleep(0.1)
        check(bool(ftk), "feishu message produced a Ticket through the kernel")
        if ftk:
            t = wait_ready(rt, ftk["id"], timeout=20)
            check(t.get("status") == "ended", "feishu Ticket ended")
            time.sleep(0.5)
            out = rt.store.q("SELECT * FROM feishu_out WHERE kind LIKE 'report:%' ORDER BY at DESC LIMIT 1")
            check(bool(out) and "✅" in out[0]["body"], "result pushed back to the same Feishu chat")
            meta = rt.store.q1("SELECT meta FROM thread WHERE key='feishu/chat-oc_test'")
            check("feishu_chat_id" in (meta["meta"] if meta else ""), "chat binding stored on the Thread")

        # dedupe: the same event delivered twice creates one Trigger
        import json as _json  # noqa: E402
        payload = {"schema": "2.0", "header": {"event_id": "evt_dedupe_test",
                                               "event_type": "im.message.receive_v1"},
                   "event": {"sender": {"sender_id": {"open_id": "ou_sim_erik"}},
                             "message": {"message_id": "om_1", "chat_id": "oc_test",
                                         "message_type": "text",
                                         "content": _json.dumps({"text": "/tickets"})}}}
        raw = _json.dumps(payload).encode("utf-8")
        c1, b1 = fs.handle_webhook({}, raw)
        c2, b2 = fs.handle_webhook({}, raw)
        check(c1 == 200 and c2 == 200 and b2.get("duplicate"), "duplicate Feishu event ignored")

        # a stranger is refused by the Source allowlist, and no Ticket is created
        before = rt.store.q("SELECT COUNT(*) n FROM ticket WHERE thread_key='feishu/chat-oc_stranger'")[0]["n"]
        r2 = fs.simulate("给我一张工单", chat_id="oc_stranger", actor="feishu:ou_stranger")
        time.sleep(0.6)
        after = rt.store.q("SELECT COUNT(*) n FROM ticket WHERE thread_key='feishu/chat-oc_stranger'")[0]["n"]
        check(r2["status"] == 200 and before == after, "unlisted Feishu actor creates no Ticket")
        check(fs.counters["refused"] >= 1, "refusal counted")

        # one-click allowlist bootstrap: a new policy version, and the next message works
        res = fs.allow_actor("feishu:ou_stranger")
        check(res["added"] and res["version"] > 2, f"allow_actor bumps policy to v{res['version']}")
        fs.simulate("给我一张工单", chat_id="oc_stranger", actor="feishu:ou_stranger")
        time.sleep(1.0)
        after2 = rt.store.q("SELECT COUNT(*) n FROM ticket WHERE thread_key='feishu/chat-oc_stranger'")[0]["n"]
        check(after2 == 1, "allowed actor now gets a Ticket")

        # url_verification challenge and signature check
        chal = _json.dumps({"type": "url_verification", "challenge": "abc123", "token": "t"}).encode()
        code, body = fs.handle_webhook({}, chal)
        check(code == 200 and body.get("challenge") == "abc123", "url_verification echoed")
        fs.cfg.encrypt_key = "secret"
        ok, why = fs.verify({"x-lark-request-timestamp": "1", "x-lark-request-nonce": "n",
                             "x-lark-signature": "deadbeef"}, chal)
        check(not ok and why == "signature_mismatch", "bad signature rejected")
        good = __import__("hashlib").sha256(b"1n" + b"secret" + chal).hexdigest()
        ok2, _ = fs.verify({"x-lark-request-timestamp": "1", "x-lark-request-nonce": "n",
                            "x-lark-signature": good}, chal)
        check(ok2, "valid signature accepted")
        fs.cfg.encrypt_key = ""

        # a forged callback with the wrong verification token is refused
        fs.cfg.verification_token = "vt_real"
        forged = _json.dumps({"schema": "2.0",
                              "header": {"event_id": "evt_forged", "token": "wrong",
                                         "event_type": "im.message.receive_v1"},
                              "event": {"sender": {"sender_id": {"open_id": "ou_sim_erik"}},
                                        "message": {"message_id": "om_f", "chat_id": "oc_test",
                                                    "content": _json.dumps({"text": "/status"})}}}).encode()
        code, body = fs.handle_webhook({}, forged)
        check(code == 403 and "token" in (body.get("error") or ""), "wrong verification token refused")
        fs.cfg.verification_token = ""

        # 8. poller: millisecond create_time must not push the cursor into the future
        class FakeClient:
            def chats(self):
                return [{"chat_id": "oc_sim_fake", "name": "fake"}]

            def history(self, chat_id, start_time):
                assert start_time <= int(time.time()), f"cursor in the future: {start_time}"
                return [{"message_id": "om_fake_1", "create_time": "1795189946613",
                         "sender": {"id": "ou_sim_erik", "sender_type": "user"},
                         "msg_type": "text", "deleted": False,
                         "body": {"content": _json.dumps({"text": "/status"})}}]

        real_client = fs.client
        fs.client = FakeClient()
        fs.cfg.poll_chats = []
        try:
            seen = fs.poll_once()
            check(seen == 1, f"poller ingested one message (got {seen})")
            cur = fs.store.q1("SELECT value FROM kv WHERE key='feishu:last_seen:oc_sim_fake'")
            check(bool(cur) and int(cur["value"]) <= int(time.time()), "poll cursor stays in the past")
        finally:
            fs.client = real_client

        # 9. carbon maths is self-consistent
        b = rt.store.q1("SELECT * FROM batch WHERE id='B-2026-11'")
        doc = carbon.compute(b)
        s = doc["totals"]
        check(abs(s["total"] - (s["scope1"] + s["scope2"] + s["scope3"])) < 1e-6, "totals add up")
        check(abs(doc["intensity_kgco2e_per_kg"] - s["total"] / b["kg_green"]) < 1e-4, "intensity = total/kg")
        check(doc["warnings"] and "unverified" in doc["warnings"][0], "warnings travel with the numbers")

        # 8. a `progress` Report keeps the Assignment alive and the Ticket open
        from engine import Engine  # noqa: E402  (kernel unit, isolated store)
        from policy import Policy  # noqa: E402
        from store import Store  # noqa: E402
        eng_dir = os.path.join(var, "unit")
        st = Store(os.path.join(eng_dir, "db.sqlite"))
        eng = Engine(st, Policy(st), eng_dir)
        eng.intake(source="aero", thread_key="aero/cabin-U1", kind="iot.anomaly",
                   text="EC over threshold", actor="sim.aero", severity="high",
                   payload={"cabin": "U1"})
        eng.passes()
        tkt = st.q1("SELECT * FROM ticket LIMIT 1")
        asg = st.q1("SELECT * FROM assignment LIMIT 1")
        check(bool(tkt and asg), "unit kernel created ticket + assignment")
        if tkt and asg:
            eng.report(tkt["id"], asg["id"], "progress", "halfway through the window")
            a2 = st.q1("SELECT * FROM assignment WHERE id=?", (asg["id"],))
            t2 = eng.ticket(tkt["id"])
            check(a2["status"] != "ended", f"progress report keeps the assignment alive (status={a2['status']})")
            check(t2["status"] == "open", "progress report keeps the ticket open")
            eng.report(tkt["id"], asg["id"], "ready", "done")
            check(eng.ticket(tkt["id"])["status"] == "ended", "ready report ends the ticket")
        st.close()
    finally:
        rt.stop()

    print()
    if fails:
        print(f"{len(fails)} check(s) failed:")
        for f in fails:
            print("  -", f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
