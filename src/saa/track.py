"""Live record of the model's positioning.

Every automatic run in a new month stores the tactical model portfolio with
the date of the decision. The position applies from the following month
onward and is never changed afterwards, so the record contains no hindsight.
Performance is computed from the monthly return series of the model; if a
return is revised later (for example when index data replace an ETF bridge),
the record uses the revised figure.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / "data" / "track" / "positionen.csv"
OUT = ROOT / "docs" / "data" / "track.json"
ORDER = ["cash", "bund", "credit", "eq_eu", "eq_us", "eq_em", "gold"]


def _read() -> list[dict]:
    if not FILE.exists():
        return []
    with open(FILE, newline="") as f:
        return list(csv.DictReader(f))


def record(weights: dict, signals_as_of: str, today: date | None = None, force: bool = False) -> bool:
    """Append the position decided today. Only on the automatic run (or when
    forced), and only once per month."""
    if not force and os.environ.get("GITHUB_ACTIONS") != "true":
        return False
    today = today or date.today()
    applies = (pd.Period(today, "M") + 1).strftime("%Y-%m")
    rows = _read()
    if any(r["gilt_fuer"] == applies for r in rows):
        return False
    total = sum(weights["total"])
    row = {"entschieden": today.isoformat(), "signale_zum": signals_as_of, "gilt_fuer": applies}
    for k, t, s, r in zip(weights["keys"], weights["total"], weights["strat"], weights["ref"]):
        row[f"modell_{k}"] = round(t / total, 4)
        row[f"strategisch_{k}"] = round(s, 4)
        row[f"referenz_{k}"] = round(r, 4)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    new = not FILE.exists()
    with open(FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    return True


def performance(model: dict) -> dict:
    rows = _read()
    out = {"positions": [], "months": [], "start": None}
    if not rows:
        OUT.write_text(json.dumps(out))
        return out
    h = model["history"]
    idx = pd.period_range(h["start"], periods=len(h["returns"]["cash"]), freq="M")
    rets = pd.DataFrame({k: h["returns"][k] for k in ORDER}, index=idx)
    out["start"] = rows[0]["entschieden"]
    for r in rows:
        out["positions"].append({"decided": r["entschieden"], "signals": r["signale_zum"], "applies": r["gilt_fuer"],
                                 "model": {k: float(r[f"modell_{k}"]) for k in ORDER},
                                 "reference": {k: float(r[f"referenz_{k}"]) for k in ORDER}})
    first = pd.Period(rows[0]["gilt_fuer"], "M")
    for m in rets.index[rets.index >= first]:
        pos = [p for p in out["positions"] if pd.Period(p["applies"], "M") <= m][-1]
        rm = sum(pos["model"][k] * rets.loc[m, k] for k in ORDER)
        rr = sum(pos["reference"][k] * rets.loc[m, k] for k in ORDER)
        out["months"].append([str(m), round(rm, 5), round(rr, 5)])
    OUT.write_text(json.dumps(out))
    return out
