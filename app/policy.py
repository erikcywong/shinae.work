"""Versioned policy: who may originate work, which rules accept it, how far it may go.

Mirrors src/policy.ts of dsh-superagent: one immutable document per version,
hashed so every Mandate can name the exact rules it relied on.
"""
from __future__ import annotations

import hashlib
import json
import os

from store import Store, dumps, loads, utcnow

DEFAULT_POLICY = {
    "version": 1,
    "paused": False,
    "mode": "auto",
    "eval_timeout_s": 120,
    "watchdog_stale_s": 90,
    "sources": {
        "aero": {
            "enabled": True,
            "label": "AeroCabin IoT",
            "allow": ["erik", "iot.gateway", "sim.aero"],
        },
        "field": {
            "enabled": True,
            "label": "Field & Harvest Log",
            "allow": ["erik", "field.log", "sim.field"],
        },
        "carbon": {
            "enabled": True,
            "label": "Carbon Registry Feed",
            "allow": ["erik", "registry.feed"],
        },
        "brand": {
            "enabled": True,
            "label": "Brand Inbox",
            "allow": ["erik", "brand.inbox"],
        },
        "feishu": {
            "enabled": True,
            "label": "Feishu (Lark)",
            # Source-local identities: open_ids, never mapped onto panel names.
            "allow": ["feishu:ou_sim_erik", "feishu:ou_erik"],
        },
    },
    "rules": [
        {
            "id": "iot.drift.high",
            "enabled": True,
            "match": {"kind": ["iot.anomaly"], "severity": ["high", "critical"]},
            "outcome": "accept",
            "strength": "explicit",
            "title": "Cabin {cabin}: root-cause drifted EC/pH and re-derive nutrient recipe",
            "scope": ["telemetry.read", "carbon.compute", "file.write"],
            "max_minutes": 30,
        },
        {
            "id": "harvest.recorded",
            "enabled": True,
            "match": {"kind": ["harvest.recorded"]},
            "outcome": "accept",
            "strength": "explicit",
            "title": "Batch {batch}: compute footprint, chain ledger entry, refresh dossier",
            "scope": ["carbon.compute", "ledger.append", "dossier.render", "file.write"],
            "max_minutes": 45,
        },
        {
            "id": "factor.updated",
            "enabled": True,
            "match": {"kind": ["factor.updated"]},
            "outcome": "accept",
            "strength": "explicit",
            "title": "Grid/nutrient factor changed: re-run ledger for batches on {region}",
            "scope": ["carbon.compute", "ledger.append", "file.write"],
            "max_minutes": 45,
        },
        {
            "id": "human.message",
            "enabled": True,
            "match": {"kind": ["human.message"]},
            "outcome": "accept",
            "strength": "explicit",
            "title": "Human request: {text}",
            "scope": ["telemetry.read", "carbon.compute", "ledger.append", "dossier.render", "file.write"],
            "max_minutes": 20,
        },
        {
            # Proactive work: only ever accepted from a rule the team wrote.
            # In "record" mode this produces a would_accept decision and no Ticket.
            "id": "brand.proactive",
            "enabled": True,
            "match": {"kind": ["brand.question"]},
            "outcome": "accept",
            "strength": "inferred",
            "title": "Brand inbox: draft a bilingual answer about {topic}",
            "scope": ["dossier.render", "file.write"],
            "max_minutes": 20,
        },
        {
            "id": "iot.info",
            "enabled": True,
            "match": {"kind": ["iot.info"]},
            "outcome": "ignore",
            "strength": "explicit",
            "reason": "below_threshold",
            "scope": [],
        },
    ],
}

POLICY_MUTABLE = ("paused", "mode", "eval_timeout_s", "watchdog_stale_s", "sources", "rules")


def canonical(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k not in ("hash", "at")}
    return dumps(body)


def policy_hash(doc: dict) -> str:
    return hashlib.sha256(canonical(doc).encode("utf-8")).hexdigest()


class PolicyError(ValueError):
    pass


class Policy:
    """A read-only view of one policy version, plus the write path for a new one."""

    def __init__(self, store: Store):
        self.store = store
        if not store.q1("SELECT version FROM policy ORDER BY version DESC LIMIT 1"):
            self._insert(DEFAULT_POLICY)
        else:
            self._ensure_defaults()
        self.doc = self.current()

    def _ensure_defaults(self) -> None:
        """Forward-compatible policy migration: new Sources and rules arrive as a new version.

        Existing deployments (v1, v2, ...) gain the Feishu Source without losing
        their own edits; every Ticket still records the exact version it relied on.
        """
        cur = self.current()
        body = {k: cur[k] for k in POLICY_MUTABLE if k in cur}
        changed = False
        for sid, s in DEFAULT_POLICY["sources"].items():
            if sid not in body["sources"]:
                body["sources"][sid] = s
                changed = True
        env_allow = [x.strip() for x in os.environ.get("FEISHU_ALLOW", "").split(",") if x.strip()]
        if env_allow:
            norm = [a if ":" in a else f"feishu:{a}" for a in env_allow]
            feishu = body["sources"].setdefault("feishu", dict(DEFAULT_POLICY["sources"]["feishu"]))
            if feishu.get("allow") != norm:
                feishu["allow"] = norm
                changed = True
        ids = {r["id"] for r in body["rules"]}
        for rule in DEFAULT_POLICY["rules"]:
            if rule["id"] not in ids:
                body["rules"].append(rule)
                changed = True
        if changed:
            body["version"] = int(cur["version"]) + 1
            self.validate(body)
            self._insert(body)

    # ---- versions -------------------------------------------------------
    def current(self) -> dict:
        row = self.store.q1("SELECT version, doc, hash, at FROM policy ORDER BY version DESC LIMIT 1")
        doc = loads(row["doc"], {})
        doc["hash"] = row["hash"]
        doc["at"] = row["at"]
        return doc

    def _insert(self, doc: dict) -> dict:
        body = {k: v for k, v in doc.items() if k not in ("hash", "at")}
        h = policy_hash(body)
        with self.store.tx() as c:
            c.execute(
                "INSERT INTO policy(version, doc, hash, at) VALUES(?,?,?,?)",
                (int(body["version"]), dumps(body), h, utcnow()),
            )
        return {**body, "hash": h}

    def bump(self, patch: dict) -> dict:
        unknown = set(patch) - set(POLICY_MUTABLE)
        if unknown:
            raise PolicyError(f"unknown policy fields: {sorted(unknown)}")
        cur = self.current()
        body = {k: v for k, v in cur.items() if k in POLICY_MUTABLE}
        body.update(patch)
        body["version"] = int(cur["version"]) + 1
        self.validate(body)
        row = self._insert(body)
        self.doc = self.current()
        return row

    def validate(self, doc: dict) -> None:
        if doc.get("mode") not in ("auto", "record"):
            raise PolicyError("mode must be auto or record")
        for r in doc.get("rules", []):
            for field in ("id", "match", "outcome", "scope"):
                if field not in r:
                    raise PolicyError(f"rule missing {field}: {r.get('id')}")
            if r["outcome"] not in ("accept", "ignore", "stop"):
                raise PolicyError(f"bad outcome in rule {r['id']}")

    # ---- admission ------------------------------------------------------
    def source_enabled(self, source: str) -> bool:
        s = self.doc["sources"].get(source)
        return bool(s and s.get("enabled"))

    def actor_allowed(self, source: str, actor: str) -> bool:
        s = self.doc["sources"].get(source) or {}
        return actor in (s.get("allow") or [])

    def gate(self, trigger: dict):
        """Deterministic first layer. Returns (admitted, reason) — no model involved."""
        if not self.source_enabled(trigger["source"]):
            return False, "source_disabled"
        if not self.actor_allowed(trigger["source"], trigger["actor"]):
            return False, "actor_not_allowed"
        return True, "admitted"

    def match_rule(self, trigger: dict, payload: dict):
        for rule in self.doc["rules"]:
            if not rule.get("enabled", True):
                continue
            m = rule["match"]
            if m.get("kind") and trigger["kind"] not in m["kind"]:
                continue
            if m.get("severity") and trigger.get("severity") not in m["severity"]:
                continue
            if m.get("thread_prefix"):
                prefixes = m["thread_prefix"]
                if not any(trigger["thread_key"].startswith(p) for p in prefixes):
                    continue
            return rule
        return None

    def title_for(self, rule: dict, trigger: dict, payload: dict) -> str:
        values = {
            "cabin": payload.get("cabin", trigger["thread_key"].split("/")[-1]),
            "batch": payload.get("batch", ""),
            "region": payload.get("region", ""),
            "topic": payload.get("topic", ""),
            "text": (trigger.get("text") or "")[:120],
        }
        try:
            return rule["title"].format(**values)
        except (KeyError, IndexError):
            return rule["title"]

    def evaluate(self, trigger: dict, payload: dict) -> dict:
        """Eval: gate then rule assessment. Returns a Decision draft (no side effects)."""
        ok, why = self.gate(trigger)
        if not ok:
            return {"outcome": "ignore", "strength": "explicit", "reason": why, "rule": None}
        rule = self.match_rule(trigger, payload)
        if rule is None:
            return {"outcome": "ignore", "strength": "explicit", "reason": "no_rule", "rule": None}
        if rule["outcome"] == "ignore":
            return {
                "outcome": "ignore",
                "strength": rule.get("strength", "explicit"),
                "reason": rule.get("reason", "rule_ignore"),
                "rule": rule,
            }
        inferred = rule.get("strength") == "inferred"
        if inferred and self.doc["mode"] == "record":
            return {
                "outcome": "ignore",
                "strength": "inferred",
                "reason": "would_accept",
                "rule": rule,
                "title": self.title_for(rule, trigger, payload),
            }
        return {
            "outcome": "accept",
            "strength": rule.get("strength", "explicit"),
            "reason": f"rule:{rule['id']}",
            "rule": rule,
            "title": self.title_for(rule, trigger, payload),
            "scope": rule.get("scope", []),
        }

    def mandate(self, trigger: dict, decision: dict) -> dict:
        return {
            "policy_version": self.doc["version"],
            "policy_hash": self.doc["hash"],
            "strength": decision["strength"],
            "rule": (decision.get("rule") or {}).get("id"),
            "scope": decision.get("scope", []),
            "granted_by": trigger["actor"],
            "via": "addressed" if trigger["kind"] == "human.message" else "rule",
            "granted_at": utcnow(),
        }
