"""Current market inputs, derived from the latest data where possible.

Some inputs have no free monthly source (regional CAPE, dividend yields).
They are kept as dated anchors in config/inputs.json and rolled forward with
the price index since the anchor: price moves the ratio one for one, while the
ten-year earnings average in the CAPE denominator grows only slowly (real
earnings growth plus inflation). Refreshing the anchors once a quarter keeps
the drift small.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd

from . import returns as R

PRICE_TICKERS = {"eq_us": ["^GSPC"], "eq_eu": ["^STOXX", "EXSA.DE"], "eq_em": ["EEM"]}


def _price_series(key: str, anchor: pd.Period) -> tuple[pd.Series, str]:
    """First price index that covers the anchor month. Unadjusted closes, so
    dividends are excluded. For the US the Shiller file (monthly averages)
    serves as a last resort."""
    y = pd.read_csv(R.RAW / "yahoo_monthly.csv", parse_dates=["date"])
    for t in PRICE_TICKERS[key]:
        d = y[y["ticker"] == t]
        if len(d) < 24:
            continue
        per = d["date"].dt.to_period("M")
        per = per.where(d["date"].dt.day < 25, per + 1)
        s = pd.Series(d["close"].astype(float).values, index=per).groupby(level=0).last()
        if anchor in s.index and s.index.is_monotonic_increasing:
            return s, t
    if key == "eq_us":
        sh = pd.read_csv(R.RAW / "shiller.csv", parse_dates=["Date"])
        s = pd.Series(sh["SP500"].astype(float).values, index=sh["Date"].dt.to_period("M"))
        if anchor in s.index:
            return s, "S&P Composite"
    raise KeyError(key)


def _roll(anchor_value: float, key: str, anchor_month: str, growth: float) -> tuple[float, dict]:
    a = pd.Period(anchor_month, "M")
    try:
        s, t = _price_series(key, a)
    except KeyError:
        return anchor_value, {"ticker": None, "move": 0.0, "months": 0}
    p0, p1 = s.loc[a], s.iloc[-1]
    months = (s.index[-1] - a).n
    factor = (p1 / p0) / (1 + growth) ** (months / 12)
    return anchor_value * factor, {"ticker": t, "move": float(p1 / p0 - 1), "months": int(months),
                                   "to": str(s.index[-1])}


def live_inputs(base: dict) -> tuple[dict, dict]:
    inp = copy.deepcopy(base)
    infl = inp["inflation_eur"]["value"]
    notes = {}

    # Bund: latest daily 10y yield of the ECB AAA curve (German and other AAA
    # issuers, within a few basis points of the Bund), more current than the
    # Bundesbank month-end series used for the return history
    y = R.ecb_series("ecb_yc_aaa.csv", "SR_10Y")
    inp["bund"]["yield"] = round(float(y.iloc[-1]) / 100, 4)
    notes["bund"] = {"date": y.index[-1].strftime("%Y-%m-%d"), "value": inp["bund"]["yield"]}

    # Money market: latest €STR, path to neutral rate (a quarter weight on today)
    try:
        e = R.ecb_series("ecb_estr.csv")
        cur = float(e.iloc[-1]) / 100
        inp["cash"]["current"] = round(cur, 4)
        notes["cash"] = {"date": e.index[-1].strftime("%Y-%m-%d"), "value": cur}
    except FileNotFoundError:
        cur = inp["cash"]["current"]
    inp["cash"]["value"] = round(0.25 * cur + 0.75 * inp["cash"]["neutral"], 4)

    # Credit: scraped yield to maturity if present
    try:
        c = json.loads((R.RAW / "credit_ytm.json").read_text())
        inp["credit"]["ytm"] = c["ytm"]
        if c.get("duration"):
            inp["credit"]["duration"] = c["duration"]
        notes["credit"] = c
    except FileNotFoundError:
        pass

    # Equities: latest published CAPE and dividend yield (Siblis Research,
    # country values aggregated with the fund's country weights), rolled
    # forward with the price index to today. Without a published value the
    # dated anchors in config/inputs.json are rolled forward instead.
    anchors = inp["anchors"]
    used = {}
    for k in ("eq_us", "eq_eu", "eq_em"):
        g = inp[k]["g_real"] + infl + max(inp[k]["net_buyback"], 0)
        sc = siblis_value(k, "cape", inp)
        if sc and 5 < sc["value"] < 80:
            base, month, src = sc["value"], sc["period"], "siblis"
        else:
            base = em_cape_anchor(inp[k]) if k == "eq_em" else inp[k]["cape"]
            month, src, sc = anchors["cape_month"], "stichtag", None
        cape, info = _roll(base, k, month, g)
        inp[k]["cape_anchor"] = round(base, 2)
        inp[k]["cape"] = round(cape, 2)
        # dividends are sticky: a higher price lowers the dividend yield one for one
        # dividend yield: MSCI factsheet (whole index, monthly), else Siblis
        # (country values, quarterly), else the dated anchor
        sd, fm = siblis_value(k, "dy", inp), msci_value(k)
        if fm:
            dy0, dmonth, dsrc = fm["dy"], fm["date"][:7], "msci"
        elif sd and 0.002 < sd["value"] < 0.1:
            dy0, dmonth, dsrc = sd["value"], sd["period"], "siblis"
        else:
            dy0, dmonth, dsrc = inp[k]["dy"], anchors["dy_month"][k], "stichtag"
        price_ratio, _ = _roll(1.0, k, dmonth, 0.0)
        inp[k]["dy"] = round(dy0 / price_ratio, 4)

        label = REGION[k]
        cov = f", {round(sc['coverage'] * 100)} % des Index" if sc and k != "eq_us" else ""
        where = "Siblis Research" if src == "siblis" else "Stichtagswert"
        inp[k]["cape_source"] = (f"{label}, {month_de(month)} ({where}{cov}), "
                                 f"mit dem Kursindex fortgeschrieben bis {month_de(info.get('to', month))}")
        dname = {"msci": "MSCI-Factsheet", "siblis": "Siblis Research", "stichtag": "Stichtagswert"}[dsrc]
        inp[k]["dy_source"] = f"{label}, {month_de(dmonth)} ({dname}), mit Kursen fortgeschrieben"
        if sc and k != "eq_us":
            inp[k]["coverage"] = round(sc["coverage"], 3)
            inp[k]["top_countries"] = sc["top"]
        used[k] = {"cape_month": month, "dy_month": dmonth, "cape_source": src, "dy_source": dsrc}
        notes[k] = {"cape": inp[k]["cape"], "anchor": inp[k]["cape_anchor"], "anchor_month": month,
                    "source": src, **info}
    inp["anchors"] = {**anchors, "regions": used}
    return inp, notes


REGION = {"eq_us": "USA", "eq_eu": "Europa", "eq_em": "Schwellenländer"}
MONTHS_DE = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."]
COUNTRY_DE = {"South Korea": "Südkorea", "India": "Indien", "Brazil": "Brasilien", "South Africa": "Südafrika",
              "Saudi Arabia": "Saudi-Arabien", "Mexico": "Mexiko", "Poland": "Polen",
              "United Arab Emirates": "Vereinigte Arabische Emirate", "United Kingdom": "Großbritannien",
              "France": "Frankreich", "Switzerland": "Schweiz", "Germany": "Deutschland",
              "Netherlands": "Niederlande", "Spain": "Spanien", "Sweden": "Schweden", "Italy": "Italien",
              "Denmark": "Dänemark", "Finland": "Finnland", "Belgium": "Belgien", "Norway": "Norwegen"}


def month_de(ym: str) -> str:
    y, m = str(ym)[:7].split("-")
    return f"{MONTHS_DE[int(m) - 1]} {y}"


def msci_value(k: str) -> dict | None:
    try:
        v = json.loads((R.RAW / "msci_fundamentals.json").read_text())[k]
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return v if 0.002 < v.get("dy", 0) < 0.1 else None


def country_weights(k: str, inp: dict) -> dict:
    """Index weights by country in percent: from the iShares fund page if
    fetched, otherwise the fallback in config/inputs.json."""
    try:
        return json.loads((R.RAW / "country_weights.json").read_text())[k]["weights"]
    except (FileNotFoundError, KeyError, ValueError):
        if k == "eq_em":
            return {c: v[1] * 100 for c, v in inp[k]["cape_countries"].items()}
        return inp[k].get("country_weights", {})


def siblis_value(k: str, measure: str, inp: dict) -> dict | None:
    """Latest published value for a region. Regions are aggregated from
    countries with index weights: CAPE through the weighted earnings yield,
    dividend yield as a weighted mean. Requires 60 % coverage."""
    path = R.RAW / "siblis.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df = df[df["measure"] == measure]
    if df.empty:
        return None
    per = df["period"].max()
    d = df[df["period"] == per].set_index("market")["value"]
    if k == "eq_us":
        return {"value": float(d["United States"]), "period": per, "coverage": 1.0} if "United States" in d else None
    w = country_weights(k, inp)
    cov = {c: x for c, x in w.items() if c in d.index}
    if not w or sum(cov.values()) < 60:
        return None
    ws = np.array(list(cov.values()))
    vs = d[list(cov)].values.astype(float)
    val = ws.sum() / (ws / vs).sum() if measure == "cape" else float((ws * vs).sum() / ws.sum())
    top = sorted(w.items(), key=lambda x: -x[1])[:2]
    return {"value": float(val), "period": per, "coverage": sum(cov.values()) / 100,
            "top": [[COUNTRY_DE.get(c, c), round(x / 100, 3)] for c, x in top]}


def em_cape_anchor(cfg: dict) -> float:
    w = np.array([v[1] for v in cfg["cape_countries"].values()])
    c = np.array([v[0] for v in cfg["cape_countries"].values()])
    return float(1.0 / ((w / c).sum() / w.sum()))
