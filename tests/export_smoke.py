"""Exports must be openable and greppable: PDF structure + zip contents.

    python tests/export_smoke.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import carbon  # noqa: E402
import export  # noqa: E402
import ledger  # noqa: E402
from store import Store  # noqa: E402


def main() -> int:
    var = os.path.join(ROOT, "var", f"export-{os.getpid()}")
    os.makedirs(var, exist_ok=True)
    st = Store(os.path.join(var, "db.sqlite"))
    with st.tx() as c:
        c.execute("INSERT INTO batch(id,name,cabin,kg_green,harvest_at,kwh,water_l,nutrient_kg,"
                  "substrate_kg,freight_tkm,region,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  ("B-TEST", "Test batch", "A1", 40.0, "2026-11-01T00:00:00Z", 2000.0, 3500.0,
                   18.0, 0.0, 100.0, "CN", ""))
    batch = st.q1("SELECT * FROM batch WHERE id='B-TEST'")
    doc = carbon.compute(batch)
    ledger.append_document(st, doc, note="export test")
    rows = st.q("SELECT * FROM ledger_entry WHERE batch_id='B-TEST' ORDER BY id")
    verify = ledger.verify(st, "B-TEST")

    fails = []
    pdf = export.batch_pdf(batch, doc, rows, verify)
    if not pdf.startswith(b"%PDF-1.4"):
        fails.append("pdf magic missing")
    if b"%%EOF" not in pdf[-10:]:
        fails.append("pdf EOF missing")
    if b"1225" not in pdf and b"1073" not in pdf and b"total" not in pdf:
        fails.append("pdf has no footprint numbers")
    if b"Not for external claims" not in pdf:
        fails.append("pdf is missing the disclaimer block")
    if len(pdf) < 1500:
        fails.append(f"pdf suspiciously small ({len(pdf)} bytes)")

    bundle = export.zenodo_bundle(batch, doc, rows, verify, carbon.methodology_doc(),
                                  "# dossier\nstub")
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        names = set(z.namelist())
        for need in ("README.txt", "methodology.json", "dossier.md", "footprint.json",
                     "ledger.json", "batch.json"):
            if need not in names:
                fails.append(f"bundle missing {need}")
        readme = z.read("README.txt").decode()
        if doc["hash"] not in readme:
            fails.append("bundle README lacks the document hash")
        if "BROKEN" in readme:
            fails.append("bundle README claims a broken chain")

    print(f"pdf {len(pdf)}B · zip {len(bundle)}B · ledger rows {len(rows)}")
    if fails:
        for f in fails:
            print("[FAIL]", f)
        return 1
    print("[ok] pdf and zenodo bundle are well formed and honest about their status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
