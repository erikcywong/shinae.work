"""Append-only, hash-chained carbon ledger.

Each computed document becomes a run of rows (one per scope item plus a total),
linked by SHA-256 over `prev_hash + canonical(row)`.  A recomputation never
edits: it appends a new revision and marks the superseded run in `note`, so a
reviewer can always see what changed and when.
"""
from __future__ import annotations

import json

from carbon import canonical, ledger_link
from store import Store, utcnow


def last_hash(store: Store, batch_id: str) -> str:
    row = store.q1("SELECT hash FROM ledger_entry WHERE batch_id=? ORDER BY id DESC LIMIT 1", (batch_id,))
    return row["hash"] if row else "0" * 64


def append_document(store: Store, doc: dict, note: str = "", kind: str = "computed") -> dict:
    """Append one run for `doc`. Returns {rows, head, total}."""
    batch_id = doc["batch_id"]
    prev = last_hash(store, batch_id)
    at = utcnow()
    rows = []
    planned = []
    for item in doc["items"]:
        planned.append(
            {
                "batch_id": batch_id,
                "at": at,
                "kind": kind,
                "scope": f"{item['scope']}/{item['category']}",
                "kgco2e": item["kgco2e"],
                "factor_id": item["factor_id"],
                "factor_value": item["factor_value"],
                "note": note,
            }
        )
    planned.append(
        {
            "batch_id": batch_id,
            "at": at,
            "kind": kind,
            "scope": "total",
            "kgco2e": doc["totals"]["total"],
            "factor_id": doc["methodology"],
            "factor_value": doc["intensity_kgco2e_per_kg"],
            "note": f"{note} | doc_hash={doc['hash']}",
        }
    )
    with store.tx() as c:
        for row in planned:
            payload = {k: row[k] for k in ("batch_id", "scope", "kgco2e", "factor_id", "factor_value", "note")}
            h = ledger_link(prev, payload)
            c.execute(
                "INSERT INTO ledger_entry(batch_id,at,kind,scope,kgco2e,factor_id,factor_value,note,prev_hash,hash)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (row["batch_id"], row["at"], row["kind"], row["scope"], row["kgco2e"],
                 row["factor_id"], row["factor_value"], row["note"], prev, h),
            )
            rows.append({"scope": row["scope"], "kgco2e": row["kgco2e"], "hash": h, "prev": prev})
            prev = h
    return {"rows": rows, "head": prev, "total": doc["totals"]["total"]}


def verify(store: Store, batch_id: str | None = None) -> dict:
    """Recompute every link. Returns {ok, checked, broken_at}."""
    sql = "SELECT * FROM ledger_entry"
    args = ()
    if batch_id:
        sql += " WHERE batch_id=?"
        args = (batch_id,)
    entries = store.q(sql + " ORDER BY id", args)
    prev_by_batch: dict[str, str] = {}
    checked = 0
    for e in entries:
        b = e["batch_id"]
        prev = prev_by_batch.get(b, "0" * 64)
        payload = {k: e[k] for k in ("batch_id", "scope", "kgco2e", "factor_id", "factor_value", "note")}
        expected = ledger_link(prev, payload)
        if e["prev_hash"] != prev or expected != e["hash"]:
            return {"ok": False, "checked": checked, "broken_at": e["id"], "batch": b}
        prev_by_batch[b] = e["hash"]
        checked += 1
    return {"ok": True, "checked": checked, "broken_at": None, "head": entries[-1]["hash"] if entries else None}


def summary(store: Store) -> list[dict]:
    """Latest run per batch, for the ledger panel."""
    batches = store.q("SELECT * FROM batch ORDER BY harvest_at DESC")
    out = []
    for b in batches:
        latest = store.q(
            "SELECT * FROM ledger_entry WHERE batch_id=? ORDER BY id DESC LIMIT 6", (b["id"],)
        )
        ver = verify(store, b["id"])
        total = next((r for r in latest if r["scope"] == "total"), None)
        out.append(
            {
                "batch": b,
                "total": total,
                "entries": list(reversed(latest)),
                "verify": ver,
            }
        )
    return out
