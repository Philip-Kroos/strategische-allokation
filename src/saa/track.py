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


HIST = ROOT / "data" / "track" / "verlauf.json"
CHANGES = ROOT / "docs" / "data" / "verlauf.json"
NOTICE = ROOT / "build" / "hinweis.md"
NAMES = {"cash": "Geldmarkt", "bund": "Bundesanleihen", "credit": "Unternehmensanleihen", "eq_eu": "Aktien Europa",
         "eq_us": "Aktien USA", "eq_em": "Aktien Schwellenländer", "gold": "Gold"}


def grade(active: float) -> str:
    """Stance as shown on the page: active weight relative to 8 points."""
    s = active / 0.08
    if s > 0.5:
        return "deutlich übergewichten"
    if s > 0.2:
        return "übergewichten"
    if s < -0.5:
        return "deutlich untergewichten"
    if s < -0.2:
        return "untergewichten"
    return "neutral"


def snapshot_of(weights: dict, model: dict, today: date) -> dict:
    total = sum(weights["total"])
    w = {k: round(t / total, 4) for k, t in zip(weights["keys"], weights["total"])}
    ref = dict(zip(weights["keys"], weights["ref"]))
    sig = model["signals"]["classes"]
    return {"date": today.isoformat(), "signals": model["signals"]["as_of"], "market": model["meta"]["as_of"][:10],
            "regime": model["meta"]["regime"]["current"], "corr": model["signals"]["corr_now"],
            "weights": w,
            "stance": {k: grade(w[k] - ref[k]) for k in ORDER if k != "cash"},
            "trend": {k: sig[k]["trend"] for k in ORDER if k != "cash"},
            "expected": {a["key"]: a["expected"] for a in model["assets"]},
            "cape": model["cape"]["current"]}


def snapshot(weights: dict, model: dict, today: date | None = None, force: bool = False) -> dict:
    """Store the state of this run (automatic runs only) and write the
    comparison with the last state at least ten days older for the page.
    If a stance or the regime changed, build/hinweis.md is written; the
    workflow turns it into a GitHub notification."""
    today = today or date.today()
    hist = json.loads(HIST.read_text()) if HIST.exists() else []
    now = snapshot_of(weights, model, today)
    if force or os.environ.get("GITHUB_ACTIONS") == "true":
        hist = [h for h in hist if h["date"] != now["date"]] + [now]
        HIST.parent.mkdir(parents=True, exist_ok=True)
        HIST.write_text(json.dumps(hist, ensure_ascii=False, indent=1))
    def notes(prev: dict | None) -> list[str]:
        if not prev:
            return []
        out = [f"{NAMES[k]}: {prev['stance'].get(k, 'neu')} → {now['stance'][k]}"
               for k in ORDER if k != "cash" and prev["stance"].get(k) != now["stance"][k]]
        if prev["regime"] != now["regime"]:
            out.append("Korrelationsregime gewechselt: Aktien und Bundesanleihen laufen jetzt "
                       + ("gleichgerichtet." if now["regime"] == "pos" else "gegenläufig."))
        return out

    # the page compares with the state at least ten days earlier
    older = [h for h in hist if (today - date.fromisoformat(h["date"])).days >= 10]
    prev = older[-1] if older else None
    out = {"now": now, "prev": prev, "notes": notes(prev)}
    CHANGES.write_text(json.dumps(out, ensure_ascii=False))
    # the notification only reports what is new since the last run
    last = [h for h in hist if h["date"] < now["date"]]
    new = notes(last[-1] if last else None)
    if new and os.environ.get("GITHUB_ACTIONS") == "true":
        NOTICE.parent.mkdir(exist_ok=True)
        moves = "\n".join(f"- {n}" for n in new)
        NOTICE.write_text(f"Änderungen gegenüber dem Lauf vom {last[-1]['date']}:\n\n{moves}\n\n"
                          "https://philip-kroos.github.io/strategische-allokation/\n")
    return out


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
