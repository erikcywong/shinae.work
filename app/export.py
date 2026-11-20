"""Exports: a one-page PDF per batch and a Zenodo-ready bundle, both dependency-free.

The PDF is written by hand (PDF 1.4, Helvetica, uncompressed streams) so the text
stays greppable and the file needs no libraries. Every page carries the draft
disclaimer: an export must never look more authoritative than the data behind it.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

DISCLAIMER = ("DRAFT — factor set unverified, cradle-to-gate only, no third-party verification. "
              "Not valid for external carbon labels, offsets or trading.")


def _esc(text: str) -> str:
    """PDF string escaping + Latin-1 fallback (Helvetica cannot render CJK)."""
    out = []
    for ch in str(text):
        if ch in "()\\":
            out.append("\\" + ch)
        elif ch == "\n":
            out.append(" ")
        elif ord(ch) < 256:
            out.append(ch)
        else:
            out.append("?")
    return "".join(out)


class Page:
    def __init__(self):
        self.ops: list[str] = []

    def text(self, x: float, y: float, s: str, size: float = 9, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        self.ops.append(f"BT /{font} {size} Tf {x:.1f} {y:.1f} Td ({_esc(s)}) Tj ET")

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.5) -> None:
        self.ops.append(f"{width} w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S")

    def rect(self, x: float, y: float, w: float, h: float, fill: float = 0.94) -> None:
        self.ops.append(f"{fill} g {x:.1f} {y:.1f} {w:.1f} {h:.1f} re f 0 g")

    def stream(self) -> str:
        return "\n".join(self.ops)


def _build_pdf(pages: list[Page], title: str) -> bytes:
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    n_pages = len(pages)
    font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    page_ids = []
    content_ids = []
    pages_id_placeholder = len(objects) + 2 * n_pages + 1
    for p in pages:
        data = p.stream().encode("latin-1", "replace")
        content_ids.append(add(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"))
    for _ in range(n_pages):
        page_ids.append(add(b""))
    pages_id = add(b"")
    catalog_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    for i, pid in enumerate(page_ids):
        objects[pid - 1] = (f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
                            f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> "
                            f"/Contents {content_ids[i]} 0 R >>").encode()
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Count {n_pages} /Kids [{kids}] >>".encode()
    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write((f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R "
               f"/Info << /Title ({_esc(title)}) /Producer (Coffee Super-Agent OS) >> >>\n"
               f"startxref\n{xref}\n%%EOF\n").encode())
    return out.getvalue()


def batch_pdf(batch: dict, doc: dict, ledger_rows: list[dict], verify: dict) -> bytes:
    """One page: identity, activity data, itemised footprint, chain head, disclaimer."""
    p = Page()
    y = 800
    p.text(48, y, "Coffee Super-Agent OS — batch footprint", 16, bold=True)
    y -= 16
    p.text(48, y, f"{batch['id']} · {batch.get('name', '')}", 10)
    y -= 12
    p.text(48, y, f"harvest {batch.get('harvest_at', '—')} · region {batch.get('region', '—')} · "
                  f"{batch.get('kg_green', 0)} kg green", 8)
    y -= 22

    p.text(48, y, "Activity data", 10, bold=True)
    y -= 14
    rows = [
        ("electricity", f"{batch.get('kwh', 0)} kWh"),
        ("water", f"{batch.get('water_l', 0)} L"),
        ("nutrient salts", f"{batch.get('nutrient_kg', 0)} kg"),
        ("substrate", f"{batch.get('substrate_kg', 0)} kg"),
        ("inbound freight", f"{batch.get('freight_tkm', 0)} t-km"),
    ]
    for label, value in rows:
        p.text(56, y, label, 9)
        p.text(200, y, value, 9)
        y -= 12
    y -= 8

    p.text(48, y, "Itemised footprint", 10, bold=True)
    y -= 14
    p.line(48, y + 8, 547, y + 8, 0.8)
    for x, head in ((56, "scope/item"), (200, "qty"), (300, "factor"), (430, "factor value"), (510, "kgCO2e")):
        p.text(x, y, head, 8, bold=True)
    y -= 12
    for item in doc.get("items", []):
        p.text(56, y, f"{item['scope']}/{item['category']}", 8)
        p.text(200, y, f"{item['qty']} {item['unit']}", 8)
        p.text(300, y, item["factor_id"], 8)
        p.text(430, y, f"{item['factor_value']} ({item['factor_status']})", 8)
        p.text(510, y, f"{item['kgco2e']}", 8)
        y -= 11
        if y < 300:
            break
    p.line(48, y + 8, 547, y + 8, 0.5)
    y -= 6
    totals = doc.get("totals", {})
    p.text(56, y, "scope 1 / 2 / 3", 9, bold=True)
    p.text(200, y, f"{totals.get('scope1', 0)} / {totals.get('scope2', 0)} / {totals.get('scope3', 0)}", 9)
    y -= 14
    p.text(56, y, "total", 10, bold=True)
    p.text(200, y, f"{totals.get('total', 0)} kgCO2e", 10, bold=True)
    p.text(360, y, f"intensity {doc.get('intensity_kgco2e_per_kg', 0)} /kg", 10)
    y -= 22

    p.text(48, y, "Audit trail", 10, bold=True)
    y -= 14
    p.text(56, y, f"methodology {doc.get('methodology')}", 8)
    y -= 11
    p.text(56, y, f"document hash {doc.get('hash', '')[:32]}…", 8)
    y -= 11
    head = ledger_rows[-1]["hash"] if ledger_rows else "—"
    p.text(56, y, f"ledger head {head[:32]}…  rows {len(ledger_rows)}  chain "
                  f"{'intact' if verify.get('ok') else 'BROKEN'}", 8)
    y -= 20

    p.rect(48, y - 28, 499, 36)
    p.text(56, y - 8, "Not for external claims", 9, bold=True)
    p.text(56, y - 20, DISCLAIMER[:120], 7)
    y -= 40
    p.text(56, y, DISCLAIMER[120:], 7)
    p.text(48, 40, f"generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} · "
                   f"coffee-super-agent-os export", 7)
    return _build_pdf([p], f"{batch['id']} footprint (draft)")


def zenodo_bundle(batch: dict, doc: dict, ledger_rows: list[dict], verify: dict,
                  methodology: dict, dossier_md: str) -> bytes:
    """A zip a reviewer can unzip and re-verify without our software running."""
    buf = io.BytesIO()
    files = {
        "README.txt": "\n".join([
            f"Batch {batch['id']} — carbon footprint package",
            "",
            "Contents:",
            "  methodology.json      methodology + factor table (draft, unverified)",
            "  dossier.md            human-readable methodology",
            "  footprint.json        computed footprint for this batch",
            "  ledger.json           every chained row + verification result",
            "  batch.json            activity data as fed to the computation",
            "",
            f"methodology hash: {methodology.get('hash')}",
            f"document hash:    {doc.get('hash')}",
            f"ledger head:      {ledger_rows[-1]['hash'] if ledger_rows else '—'}",
            f"chain verify:     {'intact' if verify.get('ok') else 'BROKEN'} "
            f"({verify.get('checked', 0)} rows)",
            "",
            "Status: DRAFT. Factors are reference-grade and unverified; the boundary is",
            "cradle-to-gate. Do not cite these numbers in an external carbon label.",
            "",
            "Cite as: Coffee Super-Agent OS (2026). Aeroponic coffee PCF dossier v0.1-draft.",
            "DOI: <to be minted on Zenodo>",
            "",
        ]),
        "methodology.json": json.dumps(methodology, ensure_ascii=False, indent=2),
        "dossier.md": dossier_md,
        "footprint.json": json.dumps(doc, ensure_ascii=False, indent=2),
        "ledger.json": json.dumps({"rows": ledger_rows, "verify": verify}, ensure_ascii=False, indent=2),
        "batch.json": json.dumps(batch, ensure_ascii=False, indent=2),
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()
