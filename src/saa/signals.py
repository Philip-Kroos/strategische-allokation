"""Tactical signals per asset class and a backtest of the trend overlay.

Two signals, each scaled to [-1, 1]:

Bewertung (slow): how cheap the asset is relative to its own history or to a
    fair value. Equities: log distance between current and fair CAPE.
    Bunds: real yield (nominal minus 2 % inflation target) against the
    history of ex-post real yields since 1990. Credit: spread over the
    AAA curve against a normal level. Gold: percentile of the real price.

Trend (fast): 12-month return over cash divided by 36-month volatility,
    i.e. a time-series momentum signal. Clipped at +/-1.5 and rescaled.

Valuation and trend work on different horizons. Tested as a monthly tilt
(backtest_combined, no look-ahead), valuation lost money from 1993 on while
trend added about one percentage point a year. The model therefore uses
valuation only for the strategic weights, through the ten-year expected
returns, and trend alone for the tactical tilt.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import returns as R

TILT = {"cash": 0.0, "bund": 0.05, "credit": 0.03, "eq_eu": 0.05, "eq_us": 0.05, "eq_em": 0.03, "gold": 0.03}
REF = {"cash": 0.05, "bund": 0.20, "credit": 0.15, "eq_eu": 0.22, "eq_us": 0.23, "eq_em": 0.08, "gold": 0.07}
COST = 0.001  # one-way cost per unit turnover


def trend_score(rets: pd.DataFrame) -> pd.DataFrame:
    lr = np.log1p(rets)
    ex12 = lr.rolling(12).sum().sub(lr["cash"].rolling(12).sum(), axis=0)
    vol = rets.rolling(36).std() * np.sqrt(12)
    s = (ex12 / vol).clip(-1.5, 1.5) / 1.5
    s["cash"] = 0.0
    return s


def valuation_scores(inputs: dict, em_cape: float, aaa5: float, gold_pct: float) -> dict:
    out = {}
    for k in ("eq_eu", "eq_us", "eq_em"):
        cape = em_cape if k == "eq_em" else inputs[k]["cape"]
        fair = inputs[k]["cape_fair"]
        out[k] = {"score": float(np.clip(np.log(fair / cape) / np.log(1.5), -1, 1)),
                  "cape": cape, "fair": fair}

    y = R.bund_yield_10y()
    cpi = R.german_cpi()
    real_hist = (y - cpi.pct_change(12) * 100).dropna().loc["1990":]
    real_now = inputs["bund"]["yield"] * 100 - inputs["inflation_eur"]["value"] * 100
    pct = float((real_hist <= real_now).mean())
    out["bund"] = {"score": 2 * pct - 1, "real_yield": real_now / 100, "pct": pct,
                   "median": float(real_hist.median()) / 100}

    spread = inputs["credit"]["ytm"] - aaa5
    normal = 0.012
    out["credit"] = {"score": float(np.clip((spread - normal) / 0.008, -1, 1)), "spread": spread, "normal": normal}

    out["gold"] = {"score": 1 - 2 * gold_pct, "pct": gold_pct}
    out["cash"] = {"score": 0.0}
    return out


def overlay_weights(scores: pd.DataFrame, order: list) -> pd.DataFrame:
    w = pd.DataFrame(index=scores.index, columns=order, dtype=float)
    for k in order:
        w[k] = REF[k] + TILT[k] * scores[k]
    # residual goes into / comes out of cash so weights sum to one
    w["cash"] = 1 - w.drop(columns="cash").sum(axis=1)
    return w.clip(lower=0)


def backtest(rets: pd.DataFrame, order: list) -> dict:
    s = trend_score(rets[order]).shift(1).dropna()
    r = rets.loc[s.index, order]
    w_tac = overlay_weights(s, order)
    w_ref = pd.DataFrame([REF] * len(r), index=r.index)[order]
    turnover = w_tac.diff().abs().sum(axis=1).fillna(0)
    r_tac = (w_tac * r).sum(axis=1) - COST * turnover
    r_ref = (w_ref * r).sum(axis=1)

    def stats(x):
        v = (1 + x).cumprod()
        return {
            "cagr": float(v.iloc[-1] ** (12 / len(x)) - 1),
            "vol": float(x.std() * np.sqrt(12)),
            "sharpe": float(((x - rets.loc[x.index, "cash"]).mean() * 12) / (x.std() * np.sqrt(12))),
            "mdd": float((v / v.cummax() - 1).min()),
        }

    diff = r_tac - r_ref
    yearly = (1 + diff).groupby(diff.index.year).prod() - 1
    t_stat = float(diff.mean() / diff.std() * np.sqrt(len(diff)))
    path_t = (1 + r_tac).cumprod()
    path_r = (1 + r_ref).cumprod()
    return {
        "start": r.index[0].strftime("%Y-%m"), "end": r.index[-1].strftime("%Y-%m"),
        "tactical": stats(r_tac), "reference": stats(r_ref),
        "excess_pa": float(diff.mean() * 12), "te": float(diff.std() * np.sqrt(12)),
        "ir": float(diff.mean() * 12 / (diff.std() * np.sqrt(12))), "t_stat": t_stat,
        "hit_years": float((yearly > 0).mean()), "turnover_pa": float(turnover.mean() * 12),
        "path": [[d.strftime("%Y-%m"), round(float(a), 4), round(float(b), 4)]
                 for d, a, b in zip(r.index[::3], path_t.iloc[::3], path_r.iloc[::3])],
        "tilts": TILT, "cost": COST,
    }


# --------------------------------------------------------------------------
# Valuation history without look-ahead: every fair value and percentile uses
# only data available at that month.

def valuation_history(index: pd.DatetimeIndex, shiller: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=index, columns=["eq_us", "bund", "gold"])

    # US: CAPE against the expanding median since 1950
    cape = shiller["PE10"].replace(0, np.nan)
    price = shiller["SP500"]
    last = cape.last_valid_index()
    # after the last published CAPE the ratio moves with the price, while the
    # ten-year earnings average grows at its trailing ten-year rate
    e10 = (price / cape).dropna()
    g = (e10.iloc[-1] / e10.iloc[-121]) ** (1 / 10) - 1
    ext = price.loc[last:].iloc[1:]
    months = np.arange(1, len(ext) + 1)
    cape_ext = pd.Series(ext.values / (e10.iloc[-1] * (1 + g) ** (months / 12)), index=ext.index)
    cape_full = pd.concat([cape.dropna(), cape_ext])
    fair = cape_full.loc["1950":].expanding(120).median()
    s_us = np.clip(np.log(fair / cape_full) / np.log(1.5), -1, 1)
    out["eq_us"] = s_us.reindex(index).ffill()

    # Bunds: real yield against its expanding history since 1975
    y = R.bund_yield_10y()
    cpi = R.german_cpi()
    real = (y - cpi.pct_change(12) * 100).dropna().loc["1975":]
    pct = real.expanding(120).apply(lambda x: (x <= x[-1]).mean(), raw=True)
    out["bund"] = (2 * pct - 1).reindex(index).ffill()

    # Gold: real price percentile since 1975
    g_eur = R.gold_usd() / R.usd_per_eur()
    rg = (g_eur / cpi).dropna().loc["1975":]
    pg = rg.expanding(120).apply(lambda x: (x <= x[-1]).mean(), raw=True)
    out["gold"] = (1 - 2 * pg).reindex(index).ffill()
    return out.fillna(0.0)


def backtest_combined(rets: pd.DataFrame, order: list, shiller: pd.DataFrame) -> dict:
    tr = trend_score(rets[order])
    val = valuation_history(rets.index, shiller)
    comb = tr.copy()
    for k in val.columns:
        comb[k] = 0.5 * tr[k] + 0.5 * val[k]
    out = {}
    for label, sc in (("trend", tr), ("kombiniert", comb), ("bewertung", val.reindex(columns=order).fillna(0.0))):
        s = sc.shift(1).dropna()
        s = s.loc[tr.shift(1).dropna().index.intersection(s.index)]
        r = rets.loc[s.index, order]
        w = overlay_weights(s, order)
        turn = w.diff().abs().sum(axis=1).fillna(0)
        rt = (w * r).sum(axis=1) - COST * turn
        rr = (pd.DataFrame([REF] * len(r), index=r.index)[order] * r).sum(axis=1)
        d = rt - rr
        v = (1 + rt).cumprod()
        out[label] = {"excess_pa": float(d.mean() * 12), "te": float(d.std() * np.sqrt(12)),
                      "ir": float(d.mean() / d.std() * np.sqrt(12)), "t_stat": float(d.mean() / d.std() * np.sqrt(len(d))),
                      "mdd": float((v / v.cummax() - 1).min()),
                      "start": r.index[0].strftime("%Y-%m"), "end": r.index[-1].strftime("%Y-%m")}
    return out


# --------------------------------------------------------------------------
# Robustness of the trend overlay: the same test with other parameters,
# other costs and in two halves of the sample.

def _trend_variant(rets, order, lookback=12, volwin=36, tiltmul=1.0, cost=COST, lag=1, sign_only=False):
    lr = np.log1p(rets[order])
    ex = lr.rolling(lookback).sum().sub(lr["cash"].rolling(lookback).sum(), axis=0)
    if sign_only:
        s = np.sign(ex)
    else:
        vol = rets[order].rolling(volwin).std() * np.sqrt(12)
        s = (ex * 12 / lookback / vol).clip(-1.5, 1.5) / 1.5
    s["cash"] = 0.0
    s = s.shift(lag)
    w = pd.DataFrame(index=s.index, columns=order, dtype=float)
    for k in order:
        w[k] = REF[k] + TILT[k] * tiltmul * s[k]
    w["cash"] = 1 - w.drop(columns="cash").sum(axis=1)
    w = w.clip(lower=0)
    turn = w.diff().abs().sum(axis=1).fillna(0)
    rt = (w * rets[order]).sum(axis=1) - cost * turn
    rr = (pd.DataFrame([REF] * len(rets), index=rets.index)[order] * rets[order]).sum(axis=1)
    return (rt - rr).where(w.notna().all(axis=1))


def trend_robustness(rets: pd.DataFrame, order: list) -> list[dict]:
    base = _trend_variant(rets, order).dropna()
    start, end = base.index[0], base.index[-1]
    mid = pd.Timestamp("2009-12-31")
    cases = [
        ("Basis: 12 Monate, 36-Monats-Volatilität, 10 Bp. Kosten", {}, None),
        ("Rückblick 6 Monate", {"lookback": 6}, None),
        ("Rückblick 9 Monate", {"lookback": 9}, None),
        ("Nur Vorzeichen, ohne Volatilitätsskalierung", {"sign_only": True}, None),
        ("Halbe Verschiebung", {"tiltmul": 0.5}, None),
        ("Doppelte Verschiebung", {"tiltmul": 2.0}, None),
        ("Dreifache Kosten (30 Bp.)", {"cost": 0.003}, None),
        ("Signal einen Monat später umgesetzt", {"lag": 2}, None),
        (f"Nur {start.year} bis 2009", {}, (start, mid)),
        (f"Nur 2010 bis {end.year}", {}, (mid + pd.offsets.MonthEnd(1), end)),
    ]
    out = []
    for label, kw, win in cases:
        d = _trend_variant(rets, order, **kw).loc[start:end].dropna()
        if win:
            d = d.loc[win[0]:win[1]]
        yearly = (1 + d).groupby(d.index.year).prod() - 1
        out.append({"label": label, "excess_pa": float(d.mean() * 12), "ir": float(d.mean() / d.std() * np.sqrt(12)),
                    "t_stat": float(d.mean() / d.std() * np.sqrt(len(d))), "hit_years": float((yearly > 0).mean()),
                    "start": d.index[0].strftime("%Y-%m"), "end": d.index[-1].strftime("%Y-%m")})
    return out
