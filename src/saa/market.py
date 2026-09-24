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

    prev = last_known()
    checks = []

    def plausible(name, value, lo, hi, fallback):
        if value is None or not lo <= value <= hi:
            checks.append(f"{name}: Wert {value} außerhalb von {lo} bis {hi}, letzter Wert {fallback} beibehalten")
            return fallback
        return value

    # Bund: latest daily 10y yield of the ECB AAA curve (German and other AAA
    # issuers, within a few basis points of the Bund), more current than the
    # Bundesbank month-end series used for the return history
    y = R.ecb_series("ecb_yc_aaa.csv", "SR_10Y")
    inp["bund"]["yield"] = round(plausible("Bundrendite", float(y.iloc[-1]) / 100, -0.01, 0.10,
                                           prev.get("bund", inp["bund"]["yield"])), 4)
    notes["bund"] = {"date": y.index[-1].strftime("%Y-%m-%d"), "value": inp["bund"]["yield"]}

    # Money market: latest €STR, path to neutral rate (a quarter weight on today)
    try:
        e = R.ecb_series("ecb_estr.csv")
        cur = plausible("€STR", float(e.iloc[-1]) / 100, -0.01, 0.10, prev.get("estr", inp["cash"]["current"]))
        inp["cash"]["current"] = round(cur, 4)
        notes["cash"] = {"date": e.index[-1].strftime("%Y-%m-%d"), "value": cur}
    except FileNotFoundError:
        cur = inp["cash"]["current"]
    inp["cash"]["value"] = round(0.25 * cur + 0.75 * inp["cash"]["neutral"], 4)

    # Credit: scraped yield to maturity if present
    try:
        c = json.loads((R.RAW / "credit_ytm.json").read_text())
        inp["credit"]["ytm"] = plausible("Rendite Unternehmensanleihen", c["ytm"], 0.0, 0.12,
                                         prev.get("credit_ytm", inp["credit"]["ytm"]))
        if c.get("duration") and 1 < c["duration"] < 10:
            inp["credit"]["duration"] = c["duration"]
        notes["credit"] = c
    except FileNotFoundError:
        pass

    # Equities: latest published CAPE (Siblis Research, country values
    # aggregated with index weights) and dividend yield (MSCI factsheet),
    # rolled forward with the price index to today. Without a fresh value the
    # last accepted one (data/derived/bewertungen.json) is rolled forward, and
    # without that the dated fallback in config/inputs.json.
    anchors = inp["anchors"]
    used = {}
    for k in ("eq_us", "eq_eu", "eq_em"):
        g = inp[k]["g_real"] + infl + max(inp[k]["net_buyback"], 0)
        last = prev.get("regions", {}).get(k)
        label = REGION[k]

        # ---- CAPE
        sc = siblis_value(k, "cape", inp)
        cand = None
        if sc and 5 < sc["value"] < 80:
            cand = {"value": sc["value"], "month": sc["period"], "source": "siblis",
                    "coverage": sc.get("coverage"), "top": sc.get("top")}
            if last and last.get("cape_source") == "siblis" and \
                    not _consistent(k, last["cape"], last["cape_month"], cand["value"], cand["month"], g, 0.15):
                checks.append(f"CAPE {label}: neuer Wert {cand['value']:.1f} ({cand['month']}) passt nicht zur Kursentwicklung "
                              f"seit {last['cape_month']} ({last['cape']:.1f}), letzter Wert fortgeschrieben")
                cand = None
        if cand is None and last:
            cand = {"value": last["cape"], "month": last["cape_month"], "source": last["cape_source"],
                    "coverage": last.get("coverage"), "top": last.get("top")}
        if cand is None:
            base = em_cape_anchor(inp[k]) if k == "eq_em" else inp[k]["cape"]
            cand = {"value": base, "month": anchors["cape_month"], "source": "stichtag", "coverage": None, "top": None}
        cape, info = _roll(cand["value"], k, cand["month"], g)
        inp[k]["cape_anchor"] = round(cand["value"], 2)
        inp[k]["cape"] = round(cape, 2)

        # ---- dividend yield (dividends are sticky: price moves the yield one for one)
        fm, sd = msci_value(k), siblis_value(k, "dy", inp)
        dcand = None
        if fm:
            dcand = {"value": fm["dy"], "month": fm["date"][:7], "source": "msci"}
        elif sd and 0.002 < sd["value"] < 0.1:
            dcand = {"value": sd["value"], "month": sd["period"], "source": "siblis"}
        if dcand and last and last.get("dy_source") == dcand["source"] and \
                not _consistent(k, last["dy"], last["dy_month"], dcand["value"], dcand["month"], 0.0, 0.25, inverse=True):
            checks.append(f"Dividendenrendite {label}: neuer Wert {dcand['value']:.2%} ({dcand['month']}) passt nicht zur "
                          f"Kursentwicklung seit {last['dy_month']}, letzter Wert fortgeschrieben")
            dcand = None
        if dcand is None and last:
            dcand = {"value": last["dy"], "month": last["dy_month"], "source": last["dy_source"]}
        if dcand is None:
            dcand = {"value": inp[k]["dy"], "month": anchors["dy_month"][k], "source": "stichtag"}
        price_ratio, _ = _roll(1.0, k, dcand["month"], 0.0)
        inp[k]["dy"] = round(dcand["value"] / price_ratio, 4)

        names = {"siblis": "Siblis Research", "msci": "MSCI-Factsheet", "stichtag": "Stichtagswert"}
        cov = f", {round(cand['coverage'] * 100)} % des Index" if cand.get("coverage") and k != "eq_us" else ""
        inp[k]["cape_source"] = (f"{label}, {month_de(cand['month'])} ({names[cand['source']]}{cov}), "
                                 f"mit dem Kursindex fortgeschrieben bis {month_de(info.get('to', cand['month']))}")
        inp[k]["dy_source"] = f"{label}, {month_de(dcand['month'])} ({names[dcand['source']]}), mit Kursen fortgeschrieben"
        if cand.get("coverage") and k != "eq_us":
            inp[k]["coverage"] = round(cand["coverage"], 3)
            inp[k]["top_countries"] = cand["top"]
        used[k] = {"cape_month": cand["month"], "dy_month": dcand["month"], "cape_source": cand["source"],
                   "dy_source": dcand["source"], "cape": round(cand["value"], 3), "dy": round(dcand["value"], 5),
                   "coverage": cand.get("coverage"), "top": cand.get("top")}
        notes[k] = {"cape": inp[k]["cape"], "anchor": inp[k]["cape_anchor"], "anchor_month": cand["month"],
                    "source": cand["source"], **info}
    inp["anchors"] = {**anchors, "regions": used}
    notes["checks"] = checks
    notes["derived"] = {"regions": used, "bund": inp["bund"]["yield"], "estr": inp["cash"]["current"],
                        "credit_ytm": inp["credit"]["ytm"]}
    return inp, notes


DERIVED = R.RAW.parent / "derived" / "bewertungen.json"


def last_known() -> dict:
    try:
        return json.loads(DERIVED.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _consistent(k, v0, m0, v1, m1, g, tol, inverse=False) -> bool:
    """Does a new reading fit the price move since the last one? CAPE moves
    with price (less the growth of the earnings average), a dividend yield
    against it. Readings more than `tol` (log) away are rejected."""
    try:
        s, _ = _price_series(k, pd.Period(m0, "M"))
        p0, p1 = s.loc[pd.Period(m0, "M")], s.loc[pd.Period(m1, "M")]
    except KeyError:
        return True
    months = (pd.Period(m1, "M") - pd.Period(m0, "M")).n
    ratio = (p1 / p0) / (1 + g) ** (months / 12)
    expected = v0 / ratio if inverse else v0 * ratio
    return abs(np.log(v1 / expected)) <= tol


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
