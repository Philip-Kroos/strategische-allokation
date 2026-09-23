"""Tactical signals per asset class and a backtest of the trend overlay.

Two signals, each scaled to [-1, 1]:

Bewertung (slow): how cheap the asset is relative to its own history or to a
    fair value. Equities: log distance between current and fair CAPE.
    Bunds: real yield (nominal minus 2 % inflation target) against the
    history of ex-post real yields since 1990. Credit: spread over the
    AAA curve against a normal level. Gold: percentile of the real price.

Trend (fast): 12-month return over cash divided by 36-month volatility,
    i.e. a time-series momentum signal. Clipped at +/-1.5 and rescaled.

The tactical score is the average of both. Valuation has little power over
months, trend has little power over decades, which is why they are combined.
Only the trend signal has a full monthly history for every asset class, so
the backtest tests the trend overlay alone and says so.
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
