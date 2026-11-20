"""AeroCabin simulator: the Source that makes the whole system move.

The point of the demo is the *flow*, not the sensor physics: a cabin state walks
with noise, crosses a threshold, and the crossing becomes a Trigger.  Numbers
are plausible for a small aeroponic coffee nursery and are labelled as
simulated in the UI.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from store import Store, dumps, loads, utcnow

CABINS = ["A1", "B2", "C3"]
BASELINE = {"ec": 1.92, "ph": 5.82, "temp_c": 23.8, "rh": 74.0, "ppfd": 420.0,
            "energy_kwh": 4.1, "water_l": 36.0}

# thresholds the policy rules watch; kept here so the simulator can say why it fired
THRESHOLDS = {"ec_high": 2.45, "ph_high": 6.30, "water_l_high": 70.0}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Sim:
    def __init__(self, store: Store, engine, interval_s: float = 12.0, seed: int = 7):
        self.store = store
        self.engine = engine
        self.interval_s = interval_s
        self.rng = random.Random(seed)
        self._cooldown: dict[str, str] = {}

    # ------------------------------------------------------------ state
    def _state(self, cabin: str) -> dict:
        row = self.store.q1("SELECT value FROM kv WHERE key=?", (f"sim:{cabin}",))
        if row:
            return loads(row["value"], dict(BASELINE))
        return dict(BASELINE)

    def _save(self, cabin: str, st: dict) -> None:
        with self.store.tx() as c:
            c.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (f"sim:{cabin}", dumps(st)))

    # ------------------------------------------------------------ history
    def seed_history(self, hours: int = 6, step_min: int = 10) -> int:
        if self.store.q1("SELECT id FROM reading LIMIT 1"):
            return 0
        now = datetime.now(timezone.utc).replace(microsecond=0)
        n = 0
        with self.store.tx() as c:
            for i in range(int(hours * 60 / step_min), 0, -1):
                at = now - timedelta(minutes=i * step_min)
                for cabin in CABINS:
                    jitter = lambda k, s: max(0.05, BASELINE[k] + self.rng.gauss(0, s))
                    c.execute(
                        "INSERT INTO reading(cabin,at,ec,ph,water_l,temp_c,rh,ppfd,energy_kwh)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        (cabin, _iso(at), round(jitter("ec", 0.05), 3), round(jitter("ph", 0.06), 3),
                         round(max(20.0, BASELINE["water_l"] + self.rng.gauss(0, 4)), 2),
                         round(jitter("temp_c", 0.8), 2), round(jitter("rh", 2.5), 2),
                         round(jitter("ppfd", 18), 1), round(jitter("energy_kwh", 0.35), 3)),
                    )
                    n += 1
        return n

    # ------------------------------------------------------------ one tick
    def tick(self, anomaly: str | None = None) -> list[dict]:
        """Write one reading per cabin. `anomaly` forces a spike on that cabin."""
        out = []
        for cabin in CABINS:
            st = self._state(cabin)
            if anomaly == cabin:
                st["ec"] = round(st["ec"] + 0.55, 3)
                st["ph"] = round(st["ph"] + 0.35, 3)
                st["water_l"] = round(st["water_l"] + 25, 2)
                self._cooldown.pop(cabin, None)  # a forced anomaly always fires
            else:
                st["ec"] = round(min(2.9, max(1.5, st["ec"] + self.rng.gauss(0, 0.02))), 3)
                st["ph"] = round(min(6.6, max(5.2, st["ph"] + self.rng.gauss(0, 0.025))), 3)
                st["water_l"] = round(min(95.0, max(18.0, st["water_l"] + self.rng.gauss(0, 1.8))), 2)
            st["temp_c"] = round(min(29.0, max(19.0, st["temp_c"] + self.rng.gauss(0, 0.25))), 2)
            st["rh"] = round(min(92.0, max(55.0, st["rh"] + self.rng.gauss(0, 0.8))), 2)
            st["ppfd"] = round(min(520.0, max(320.0, st["ppfd"] + self.rng.gauss(0, 6))), 1)
            st["energy_kwh"] = round(max(2.5, st["energy_kwh"] + self.rng.gauss(0, 0.12)), 3)
            self._save(cabin, st)
            at = utcnow()
            with self.store.tx() as c:
                c.execute("INSERT INTO reading(cabin,at,ec,ph,water_l,temp_c,rh,ppfd,energy_kwh)"
                          " VALUES(?,?,?,?,?,?,?,?,?)",
                          (cabin, at, st["ec"], st["ph"], st["water_l"], st["temp_c"], st["rh"],
                           st["ppfd"], st["energy_kwh"]))
            out.append({"cabin": cabin, **{k: st[k] for k in ("ec", "ph", "water_l", "temp_c", "rh",
                                                              "ppfd", "energy_kwh")}, "at": at})
            self._watch(cabin, st, at)
        return out

    def _watch(self, cabin: str, st: dict, at: str) -> None:
        severity = None
        why = []
        if st["ec"] >= THRESHOLDS["ec_high"]:
            severity = "high"
            why.append(f"EC {st['ec']} mS/cm over the {THRESHOLDS['ec_high']} threshold")
        if st["ph"] >= THRESHOLDS["ph_high"]:
            severity = "high"
            why.append(f"pH {st['ph']} over the {THRESHOLDS['ph_high']} ceiling")
        if st["water_l"] >= THRESHOLDS["water_l_high"]:
            severity = severity or "high"
            why.append(f"water draw {st['water_l']} L per cycle (nozzle or recirculation fault)")
        if not severity:
            return
        last = self._cooldown.get(cabin)
        now = datetime.now(timezone.utc)
        if last and (now - datetime.fromisoformat(last)).total_seconds() < 900:
            return
        self._cooldown[cabin] = now.isoformat()
        self.engine.intake(
            source="aero",
            thread_key=f"aero/cabin-{cabin}",
            kind="iot.anomaly",
            text="; ".join(why),
            payload={"cabin": cabin, "ec": st["ec"], "ph": st["ph"], "water_l": st["water_l"],
                     "thresholds": THRESHOLDS},
            actor="sim.aero",
            severity=severity,
            thread_label=f"Cabin {cabin}",
        )

    # ------------------------------------------------------------ read side
    def cabins(self) -> list[dict]:
        out = []
        for cabin in CABINS:
            row = self.store.q1("SELECT * FROM reading WHERE cabin=? ORDER BY at DESC LIMIT 1", (cabin,))
            trend = list(reversed(self.store.q(
                "SELECT at, ec, ph, water_l, energy_kwh FROM reading WHERE cabin=? ORDER BY at DESC LIMIT 48",
                (cabin,))))
            if not row:
                continue
            drift = (row["ec"] >= THRESHOLDS["ec_high"] or row["ph"] >= THRESHOLDS["ph_high"]
                     or row["water_l"] >= THRESHOLDS["water_l_high"])
            out.append({"id": cabin, "at": row["at"], "ec": row["ec"], "ph": row["ph"],
                        "water_l": row["water_l"], "temp_c": row["temp_c"], "rh": row["rh"],
                        "ppfd": row["ppfd"], "energy_kwh": row["energy_kwh"],
                        "status": "drift" if drift else "ok", "trend": trend,
                        "thresholds": THRESHOLDS})
        return out
