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

    # Equities: roll CAPE and dividend yield forward with the price index
    anchors = inp["anchors"]
    for k in ("eq_us", "eq_eu", "eq_em"):
        g = inp[k]["g_real"] + infl + max(inp[k]["net_buyback"], 0)
        if k == "eq_em":
            base_cape = em_cape_anchor(inp[k])
            cape, info = _roll(base_cape, k, anchors["cape_month"], g)
            inp[k]["cape_anchor"] = base_cape
        else:
            cape, info = _roll(inp[k]["cape"], k, anchors["cape_month"], g)
            inp[k]["cape_anchor"] = inp[k]["cape"]
        inp[k]["cape"] = round(cape, 2)
        # dividends are sticky: a higher price lowers the dividend yield one for one
        price_ratio, _ = _roll(1.0, k, anchors["dy_month"][k], 0.0)
        inp[k]["dy"] = round(inp[k]["dy"] / price_ratio, 4)
        notes[k] = {"cape": inp[k]["cape"], "anchor": inp[k]["cape_anchor"], **info}
    return inp, notes


def em_cape_anchor(cfg: dict) -> float:
    w = np.array([v[1] for v in cfg["cape_countries"].values()])
    c = np.array([v[0] for v in cfg["cape_countries"].values()])
    return float(1.0 / ((w / c).sum() / w.sum()))
