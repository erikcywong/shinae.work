"""The kernel: one entry point, five responsibilities.

Rule kept from dsh-superagent/docs/001-domain.md: the Engine is the **only**
writer of Triggers, Threads, Decisions, Tickets and Assignments.  Everything
outside (Sources, Executors, HTTP, workers) only asks or reports.

    Source -> Trigger -> Thread -> Eval -> Decision -> Ticket -> Assignment -> Report
                                     \\-> Mandate (policy version, scope, strength)

All methods are synchronous and take the store lock for the length of one
transaction, so a reader never sees a half-created Ticket.
"""
from __future__ import annotations

import os

from policy import Policy
from store import Store, dumps, loads, new_id, utcnow

TERMINAL = ("ready", "dropped")


class Engine:
    def __init__(self, store: Store, policy: Policy, var_dir: str, bus=None):
        self.store = store
        self.policy = policy
        self.var_dir = var_dir
        self.bus = bus or (lambda topic, payload: None)
        os.makedirs(os.path.join(var_dir, "tickets"), exist_ok=True)

    # ------------------------------------------------------------------ util
    def emit(self, kind: str, subject: str = "", data: dict | None = None) -> None:
        at = utcnow()
        with self.store.tx() as c:
            c.execute(
                "INSERT INTO event(at, kind, subject, data) VALUES(?,?,?,?)",
                (at, kind, subject, dumps(data or {})),
            )
        self.bus("event", {"kind": kind, "subject": subject, "at": at, "data": data or {}})

    def enqueue(self, kind: str, key: str, payload: dict, delay_s: float = 0.0) -> None:
        from datetime import datetime, timedelta, timezone

        due = (datetime.now(timezone.utc) + timedelta(seconds=delay_s)).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        with self.store.tx() as c:
            c.execute("DELETE FROM effect WHERE kind=? AND key=? AND status='pending'", (kind, key))
            c.execute(
                "INSERT INTO effect(kind, key, payload, due_at) VALUES(?,?,?,?)",
                (kind, key, dumps(payload), due),
            )

    # ----------------------------------------------------------------- intake
    def intake(self, source: str, thread_key: str, kind: str, text: str,
               payload: dict | None = None, actor: str = "unknown",
               severity: str = "info", thread_label: str | None = None) -> dict:
        """A Source delivers one immutable Trigger. Idempotent per (source, dedupe_key)."""
        payload = payload or {}
        at = utcnow()
        tid = new_id("trg")
        revive = None
        with self.store.tx() as c:
            row = c.execute("SELECT key FROM thread WHERE key=?", (thread_key,)).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO thread(key, source, label, meta, queued, updated_at) VALUES(?,?,?,?,0,?)",
                    (thread_key, source, thread_label or thread_key, "{}", at),
                )
            open_ticket = c.execute(
                "SELECT id, latest_report FROM ticket WHERE thread_key=? AND status='open' "
                "ORDER BY created_at DESC LIMIT 1",
                (thread_key,),
            ).fetchone()
            c.execute(
                "INSERT INTO trigger(id, source, thread_key, kind, at, actor, text, payload, severity, disposition)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (tid, source, thread_key, kind, at, actor, text, dumps(payload), severity, "received"),
            )
            if open_ticket:
                # Fan-out: a live Ticket on the Thread receives the message as an Input
                # and needs no Eval.  This is the framework's Subscription rule.
                c.execute(
                    "INSERT INTO input(id, ticket_id, kind, text, at, delivered) VALUES(?,?,?,?,?,0)",
                    (new_id("inp"), open_ticket["id"], kind, text, at),
                )
                c.execute("UPDATE trigger SET disposition='fanned_out' WHERE id=?", (tid,))
                c.execute("UPDATE thread SET updated_at=? WHERE key=?", (at, thread_key))
                target = open_ticket["id"]
                # A Ticket waiting for a person resumes on the person's message instead of
                # holding the Input forever (waitsForPerson in the framework).
                last = loads(open_ticket["latest_report"], None) or {}
                if last.get("state") in ("blocked", "failed", "waiting"):
                    revive = {"ticket_id": target, "assignment_id": new_id("asg")}
                    c.execute(
                        "INSERT INTO assignment(id,ticket_id,status,heartbeat_at,attempts) VALUES(?,?,?,?,1)",
                        (revive["assignment_id"], target, "pending", at),
                    )
            else:
                c.execute("UPDATE thread SET queued=queued+1, updated_at=? WHERE key=?", (at, thread_key))
                target = None
        if revive:
            self.enqueue("launch", revive["ticket_id"], revive)
            self.emit("ticket.resumed", revive["ticket_id"], {"via": "person_message"})
        self.emit("trigger.received", tid, {"source": source, "kind": kind, "thread": thread_key,
                                            "ticket": target, "severity": severity})
        return {"status": "fanned_out" if target else "queued", "trigger_id": tid, "ticket_id": target}

    # ------------------------------------------------------------------- eval
    def passes(self) -> list[dict]:
        """One pass: every Thread with queued Triggers gets one Eval."""
        if self.policy.doc["paused"]:
            return []
        done = []
        for th in self.store.q("SELECT key FROM thread WHERE queued>0"):
            done.append(self.evaluate_thread(th["key"]))
        return [d for d in done if d]

    def evaluate_thread(self, thread_key: str) -> dict | None:
        trig = self.store.q(
            "SELECT * FROM trigger WHERE thread_key=? AND disposition='received' ORDER BY at LIMIT 1",
            (thread_key,),
        )
        if not trig:
            with self.store.tx() as c:
                c.execute("UPDATE thread SET queued=0 WHERE key=?", (thread_key,))
            return None
        t = trig[0]
        payload = loads(t["payload"], {})
        decision = self.policy.evaluate(t, payload)
        at = utcnow()
        did = new_id("dec")
        ticket_id = None
        launch = None

        with self.store.tx() as c:
            dup = c.execute(
                "SELECT id FROM ticket WHERE thread_key=? AND kind=? AND status='open' LIMIT 1",
                (thread_key, t["kind"]),
            ).fetchone()
            if decision["outcome"] == "accept" and dup:
                decision = {"outcome": "ignore", "strength": decision["strength"],
                            "reason": "duplicate_open_ticket", "rule": decision.get("rule")}
            if decision["outcome"] == "accept":
                rule = decision.get("rule") or {}
                ticket_id = new_id("tkt")
                tdir = os.path.join(self.var_dir, "tickets", ticket_id)
                os.makedirs(tdir, exist_ok=True)
                mandate = self.policy.mandate(t, decision)
                c.execute(
                    "INSERT INTO ticket(id,title,thread_key,kind,mandate,scope,status,strength,"
                    "policy_version,created_at,dir) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (ticket_id, decision["title"], thread_key, t["kind"], dumps(mandate),
                     dumps(decision.get("scope", [])), "open", decision["strength"],
                     self.policy.doc["version"], at, tdir),
                )
                aid = new_id("asg")
                c.execute(
                    "INSERT INTO assignment(id,ticket_id,status,heartbeat_at,attempts) VALUES(?,?,?,?,1)",
                    (aid, ticket_id, "pending", at),
                )
                c.execute("UPDATE trigger SET disposition='accepted' WHERE id=?", (t["id"],))
                launch = {"ticket_id": ticket_id, "assignment_id": aid}
            else:
                c.execute("UPDATE trigger SET disposition=? WHERE id=?", (decision["outcome"], t["id"]))
            c.execute(
                "INSERT INTO decision(id,trigger_id,thread_key,outcome,strength,reason,ticket_id,at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (did, t["id"], thread_key, decision["outcome"], decision["strength"],
                 decision["reason"], ticket_id, at),
            )
            c.execute("UPDATE thread SET queued=MAX(queued-1,0) WHERE key=?", (thread_key,))
        if launch:
            # queued only after the transaction commits: an effect never runs for a rolled-back Ticket
            self.enqueue("launch", launch["ticket_id"], launch)
        self.emit(
            "decision.recorded", did,
            {"outcome": decision["outcome"], "reason": decision["reason"], "ticket": ticket_id,
             "strength": decision["strength"], "thread": thread_key},
        )
        if ticket_id:
            self.emit("ticket.created", ticket_id, {"title": decision["title"],
                                                    "scope": decision.get("scope", [])})
        return {"decision": decision["outcome"], "ticket": ticket_id, "trigger": t["id"]}

    # ---------------------------------------------------------------- tickets
    def ticket(self, ticket_id: str) -> dict | None:
        row = self.store.q1("SELECT * FROM ticket WHERE id=?", (ticket_id,))
        if not row:
            return None
        row["mandate"] = loads(row["mandate"], {})
        row["scope"] = loads(row["scope"], [])
        row["latest_report"] = loads(row["latest_report"], None)
        return row

    def assignment_started(self, ticket_id: str, assignment_id: str) -> None:
        at = utcnow()
        with self.store.tx() as c:
            c.execute(
                "UPDATE assignment SET status='running', started_at=?, heartbeat_at=? WHERE id=?",
                (at, at, assignment_id),
            )
        self.emit("assignment.started", assignment_id, {"ticket": ticket_id})
        self.mark_inputs_delivered(ticket_id)

    def heartbeat(self, assignment_id: str) -> None:
        with self.store.tx() as c:
            c.execute("UPDATE assignment SET heartbeat_at=? WHERE id=?", (utcnow(), assignment_id))

    def mark_inputs_delivered(self, ticket_id: str) -> None:
        with self.store.tx() as c:
            c.execute("UPDATE input SET delivered=1 WHERE ticket_id=? AND delivered=0", (ticket_id,))

    def report(self, ticket_id: str, assignment_id: str, state: str, summary: str,
               question: str | None = None) -> dict:
        if state not in ("progress", "waiting", "ready", "blocked", "failed", "dropped"):
            raise ValueError(f"unknown report state {state}")
        at = utcnow()
        rid = new_id("rpt")
        ended = state in TERMINAL
        with self.store.tx() as c:
            c.execute(
                "INSERT INTO report(id,ticket_id,assignment_id,state,summary,question,at)"
                " VALUES(?,?,?,?,?,?,?)",
                (rid, ticket_id, assignment_id, state, summary, question, at),
            )
            if state in ("ready", "dropped", "blocked", "failed", "waiting"):
                # `progress` keeps the Assignment alive: the worker is still working,
                # only a terminal-ish report ends it (prototype 003-execution).
                c.execute(
                    "UPDATE assignment SET status='ended', ended_at=? WHERE id=?", (at, assignment_id)
                )
            c.execute(
                "UPDATE ticket SET latest_report=? WHERE id=?",
                (dumps({"state": state, "summary": summary, "at": at, "question": question}), ticket_id),
            )
            if ended:
                c.execute(
                    "UPDATE ticket SET status='ended', ended_at=?, ended_by='executor', outcome=? WHERE id=?",
                    (at, state, ticket_id),
                )
        self.emit("report.recorded", rid, {"ticket": ticket_id, "state": state})
        if ended:
            self.emit("ticket.ended", ticket_id, {"outcome": state})
        if question:
            self.attention(ticket_id, question)
        return {"report_id": rid, "ended": ended}

    def attention(self, ticket_id: str, question: str) -> None:
        """A question waiting for a person. The panel lists it first; nothing else does."""
        oid = f"attention:{ticket_id}"
        self.reply(oid, ticket_id, "panel", {"kind": "attention", "question": question})
        self.emit("attention.raised", ticket_id, {"question": question})

    def reply(self, reply_id: str, ticket_id: str | None, channel: str, body: dict) -> None:
        """Outbox: an id is never queued twice; the receipt is the dedupe proof."""
        queued = False
        with self.store.tx() as c:
            exists = c.execute("SELECT id FROM outbox WHERE id=?", (reply_id,)).fetchone()
            if exists:
                return
            c.execute(
                "INSERT INTO outbox(id,ticket_id,channel,body,status,at) VALUES(?,?,?,?,?,?)",
                (reply_id, ticket_id, channel, dumps(body), "pending", utcnow()),
            )
            queued = True
        if queued:
            self.enqueue("reply", reply_id, {"reply_id": reply_id})

    def stop_ticket(self, ticket_id: str, reason: str = "stopped by a person") -> bool:
        at = utcnow()
        with self.store.tx() as c:
            row = c.execute("SELECT status FROM ticket WHERE id=?", (ticket_id,)).fetchone()
            if not row or row["status"] == "ended":
                return False
            c.execute(
                "UPDATE ticket SET status='ended', ended_at=?, ended_by='person', outcome='stopped' WHERE id=?",
                (at, ticket_id),
            )
            c.execute("UPDATE assignment SET status='ended', ended_at=? WHERE ticket_id=? AND status IN ('pending','running')",
                      (at, ticket_id))
        self.emit("ticket.ended", ticket_id, {"outcome": "stopped", "reason": reason})
        return True

    def retry_ticket(self, ticket_id: str) -> dict | None:
        at = utcnow()
        t = self.ticket(ticket_id)
        if not t or t["status"] != "open":
            return None
        with self.store.tx() as c:
            c.execute("UPDATE assignment SET status='ended', ended_at=?, error='superseded' "
                      "WHERE ticket_id=? AND status IN ('pending','running')", (at, ticket_id))
            aid = new_id("asg")
            c.execute("INSERT INTO assignment(id,ticket_id,status,heartbeat_at,attempts) VALUES(?,?,?,?,1)",
                      (aid, ticket_id, "pending", at))
            c.execute("INSERT INTO input(id,ticket_id,kind,text,at,delivered) VALUES(?,?,?,?,?,0)",
                      (new_id("inp"), ticket_id, "retry", "A person asked to retry. Previous assignment ended.", at))
        self.enqueue("launch", ticket_id, {"ticket_id": ticket_id, "assignment_id": aid}, delay_s=0.2)
        self.emit("assignment.retried", ticket_id, {})
        return {"assignment_id": aid}

    def resume_with_message(self, ticket_id: str, text: str) -> dict | None:
        t = self.ticket(ticket_id)
        if not t:
            return None
        at = utcnow()
        rep = t.get("latest_report") or {}
        wake = t["status"] == "ended" or (t["status"] == "open" and rep.get("state") in
                                          ("waiting", "blocked", "failed"))
        with self.store.tx() as c:
            c.execute("INSERT INTO input(id,ticket_id,kind,text,at,delivered) VALUES(?,?,?,?,?,0)",
                      (new_id("inp"), ticket_id, "person", text, at))
            if t["status"] == "ended":
                c.execute("UPDATE ticket SET status='open', ended_at=NULL, ended_by=NULL, outcome=NULL WHERE id=?",
                          (ticket_id,))
            if wake:
                aid = new_id("asg")
                c.execute("INSERT INTO assignment(id,ticket_id,status,heartbeat_at,attempts) VALUES(?,?,?,?,1)",
                          (aid, ticket_id, "pending", at))
        if wake:
            self.enqueue("launch", ticket_id, {"ticket_id": ticket_id, "assignment_id": aid})
            self.emit("ticket.resumed", ticket_id, {"text": text, "was": t["status"]})
        return {"ok": True, "resumed": wake}

    # --------------------------------------------------------------- watchdog
    def running_assignments(self) -> list[dict]:
        return self.store.q("SELECT * FROM assignment WHERE status='running'")

    def interrupt(self, assignment: dict, stale_s: float) -> dict:
        """Watchdog: a worker that stopped heartbeating is not trusted to be alive."""
        at = utcnow()
        ticket_id = assignment["ticket_id"]
        attempts = int(assignment["attempts"])
        with self.store.tx() as c:
            c.execute("UPDATE assignment SET status='ended', ended_at=?, error='watchdog_stalled' WHERE id=?",
                      (at, assignment["id"]))
        self.emit("assignment.interrupted", assignment["id"],
                  {"ticket": ticket_id, "stale_s": stale_s})
        if attempts >= 3:
            self.report(ticket_id, assignment["id"], "blocked",
                        f"Worker stalled {attempts} times (>{int(stale_s)}s without heartbeat). "
                        "Automatic retries stopped; a person must decide.",
                        question="Worker keeps stalling on this Ticket. Retry, split the scope, or stop?")
            return {"retried": False}
        aid = new_id("asg")
        with self.store.tx() as c:
            c.execute(
                "INSERT INTO assignment(id,ticket_id,status,heartbeat_at,attempts) VALUES(?,?,?,?,?)",
                (aid, ticket_id, "pending", at, attempts + 1),
            )
            c.execute("INSERT INTO input(id,ticket_id,kind,text,at,delivered) VALUES(?,?,?,?,?,0)",
                      (new_id("inp"), ticket_id, "recovery",
                       "Recovery note: the previous worker stalled. Resume from the files already written "
                       "in your ticket directory; do not restart finished steps.", at))
        self.enqueue("launch", ticket_id, {"ticket_id": ticket_id, "assignment_id": aid})
        return {"retried": True, "assignment_id": aid}

    # ------------------------------------------------------------ policy sync
    def policy_changed(self) -> int:
        """Deliver a policy-change Input to every open Ticket. Mandates are not revoked."""
        self.policy.doc = self.policy.current()
        v = self.policy.doc["version"]
        open_tickets = self.store.q("SELECT id FROM ticket WHERE status='open'")
        at = utcnow()
        with self.store.tx() as c:
            for t in open_tickets:
                c.execute("INSERT INTO input(id,ticket_id,kind,text,at,delivered) VALUES(?,?,?,?,?,0)",
                          (new_id("inp"), t["id"], "policy",
                           f"Policy changed to v{v} (hash {self.policy.doc['hash'][:12]}). "
                           "Check whether the rule your Mandate relied on still holds.", at))
        self.emit("policy.changed", str(v), {"tickets": len(open_tickets)})
        return len(open_tickets)
