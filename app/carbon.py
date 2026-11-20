"""Carbon accounting for aeroponic coffee: factors, computation, dossier.

HONESTY RULES baked into the output, not just the docs:

* every factor carries a provenance record with `status` in
  {"reference", "unverified"}; nothing here is a certified factor set;
* every computed document carries `warnings` naming what must be replaced
  before the number may be used in an external carbon label;
* every document is hashed (SHA-256 over canonical JSON) so a reviewer can
  recompute and compare, and the ledger chain keeps superseded versions.
"""
from __future__ import annotations

import hashlib
import json

METHODOLOGY = {
    "id": "coffee-aeroponic-pcf",
    "version": "v0.1-draft",
    "published_at": "2026-11-20",
    "boundary": "cradle-to-gate, per harvested batch of green coffee",
    "functional_unit": "1 kg green coffee (SCA screen 15+, moisture 10-12%)",
    "gwp_set": "IPCC AR6 GWP100 (CO2e)",
    "rules": [
        "Scope 1 = on-site fuel combustion and refrigerant leakage; 0 for a fully electrified aeroponic cabin.",
        "Scope 2 = metered electricity x regional grid factor for the batch window.",
        "Scope 3 (material) = nutrient salts + substrate + packaging + inbound freight.",
        "Cut-off: inputs below 1% of modelled mass and below 0.5% of modelled footprint are excluded and listed.",
        "Allocation: a shared cabin month is allocated to batches by harvested green mass.",
        "No removals, no offsets, no avoided-emission credits are counted.",
    ],
    "invalidated_when": [
        "the grid factor changes for the batch's region (a factor.updated trigger re-runs the ledger)",
        "the nutrient supplier or formulation changes",
        "substrate is replaced mid-cycle",
        "metered kWh is replaced by an estimate",
    ],
    "status": "draft — not certified, not third-party verified, not for external carbon labels",
}

# Every factor is a claim with a provenance trail.  `status` is the honest bit.
FACTORS = {
    "grid.cn.avg.2023": {
        "value": 0.5366,
        "unit": "kgCO2e/kWh",
        "label_zh": "全国电网平均排放因子",
        "label_en": "China national grid average",
        "source": "MEE 2023 national average electricity CO2 factor (commonly cited value)",
        "status": "unverified",
        "replace_with": "the batch's provincial grid factor, or a market-based instrument",
    },
    "grid.sg.avg.2023": {
        "value": 0.4168,
        "unit": "kgCO2e/kWh",
        "label_zh": "新加坡电网平均排放因子",
        "label_en": "Singapore grid average",
        "source": "EMA grid emission factor, reference value",
        "status": "unverified",
        "replace_with": "the utility's published factor for the batch year",
    },
    "nutrient.npk.synth": {
        "value": 2.34,
        "unit": "kgCO2e/kg",
        "label_zh": "合成 NPK 水溶肥（生产+运输）",
        "label_en": "Synthetic NPK water-soluble fertiliser (cradle-to-gate)",
        "source": "literature range 1.9-3.2 kgCO2e/kg N-P-K blend; midpoint used",
        "status": "unverified",
        "replace_with": "a supplier-specific EPD",
    },
    "substrate.coir": {
        "value": 0.41,
        "unit": "kgCO2e/kg",
        "label_zh": "椰糠基质",
        "label_en": "Coir substrate",
        "source": "literature estimate for processed coir",
        "status": "unverified",
        "replace_with": "supplier EPD; aeroponic runs may use zero substrate",
    },
    "packaging.kraft": {
        "value": 1.12,
        "unit": "kgCO2e/kg",
        "label_zh": "牛皮纸+铝箔复合袋",
        "label_en": "Kraft + foil laminate bag",
        "source": "reference value for laminated paper packaging",
        "status": "unverified",
        "replace_with": "packaging supplier's factor",
    },
    "freight.road.tkm": {
        "value": 0.105,
        "unit": "kgCO2e/t-km",
        "label_zh": "公路货运",
        "label_en": "Road freight",
        "source": "GLEC-style default for rigid truck, laden",
        "status": "unverified",
        "replace_with": "carrier-reported intensity",
    },
}

REGION_FACTOR = {"CN": "grid.cn.avg.2023", "SG": "grid.sg.avg.2023"}


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def methodology_doc() -> dict:
    return {**METHODOLOGY, "factors": FACTORS, "hash": digest(METHODOLOGY)}


def factor(fid: str) -> dict:
    return FACTORS[fid]


def compute(batch: dict) -> dict:
    """Compute one batch. `batch` is a row of the `batch` table."""
    region = batch.get("region", "CN")
    grid_id = REGION_FACTOR.get(region, "grid.cn.avg.2023")
    items = []

    def add(scope, category, qty, unit, fid, note=""):
        f = factor(fid)
        items.append(
            {
                "scope": scope,
                "category": category,
                "qty": round(float(qty), 4),
                "unit": unit,
                "factor_id": fid,
                "factor_value": f["value"],
                "factor_unit": f["unit"],
                "factor_status": f["status"],
                "kgco2e": round(float(qty) * f["value"], 4),
                "note": note,
            }
        )

    add("scope2", "electricity", batch["kwh"], "kWh", grid_id, f"region {region}")
    add("scope3", "nutrient", batch["nutrient_kg"], "kg", "nutrient.npk.synth")
    add("scope3", "substrate", batch["substrate_kg"], "kg", "substrate.coir")
    add("scope3", "packaging", batch.get("packaging_kg", 0.0), "kg", "packaging.kraft")
    add("scope3", "freight", batch["freight_tkm"], "t-km", "freight.road.tkm")

    totals = {"scope1": 0.0, "scope2": 0.0, "scope3": 0.0}
    for it in items:
        totals[it["scope"]] = round(totals[it["scope"]] + it["kgco2e"], 4)
    total = round(sum(totals.values()), 4)
    kg = float(batch["kg_green"]) or 1.0
    water = float(batch.get("water_l", 0.0))
    doc = {
        "methodology": f"{METHODOLOGY['id']}/{METHODOLOGY['version']}",
        "methodology_hash": digest(METHODOLOGY),
        "batch_id": batch["id"],
        "batch_name": batch["name"],
        "region": region,
        "harvest_at": batch["harvest_at"],
        "kg_green": kg,
        "items": items,
        "totals": {**totals, "total": total},
        "intensity_kgco2e_per_kg": round(total / kg, 4),
        "water_l_per_kg": round(water / kg, 3) if water else None,
        "warnings": [
            "factor set is reference-grade only (status=unverified): replace with certified factors before any external claim",
            "cradle-to-gate only: roasting, retail, brewing and end-of-life are out of boundary",
            "allocation is by harvested green mass, not by revenue or floor area",
        ],
        "computed_at": None,  # set by the caller (engine clock), keeps the hash stable
    }
    doc["hash"] = digest({k: v for k, v in doc.items() if k != "hash"})
    return doc


def ledger_link(prev_hash: str, entry: dict) -> str:
    return hashlib.sha256((prev_hash + canonical(entry)).encode("utf-8")).hexdigest()
