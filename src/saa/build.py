"""Build docs/data/model.json from the raw data and config/inputs.json.

Run from the repository root:  PYTHONPATH=src python -m saa.build
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import returns as R
from .bonds import par_bond_price
from .cma import build_cma
from .risk import nearest_psd, rolling_stock_bond_corr, stambaugh_cov
from .valuation import fit_cape_regression, real_total_return_index
from . import signals as SG
from .market import live_inputs

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "data" / "model.json"

SAMPLE_START = "1990-08-31"
LONG = ["cash", "bund", "eq_eu", "eq_us", "eq_em", "gold"]
ORDER = [k for k, _ in R.ASSETS]
NAMES = dict(R.ASSETS)

STRESS = [
    ("Anleihecrash 1994", "1994-02", "1994-06"),
    ("Dotcom-Crash", "2000-04", "2003-03"),
    ("Finanzkrise", "2007-11", "2009-02"),
    ("Euro-Schuldenkrise", "2011-05", "2011-09"),
    ("Corona-Schock", "2020-02", "2020-03"),
    ("Zinswende", "2022-01", "2022-09"),
]


def r4(x, n=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def em_cape(cfg: dict) -> float:
    w = np.array([v[1] for v in cfg["cape_countries"].values()])
    c = np.array([v[0] for v in cfg["cape_countries"].values()])
    ey = (w / c).sum() / w.sum()
    return float(1.0 / ey)


def cov_block(rets: pd.DataFrame, credit_obs: pd.Series, months: pd.DatetimeIndex | None = None):
    long = rets[LONG]
    if months is not None:
        long = long.loc[long.index.intersection(months)]
    cov, info = stambaugh_cov(long, credit_obs)
    cov = cov.loc[ORDER, ORDER]
    cov = pd.DataFrame(nearest_psd(cov.values), index=ORDER, columns=ORDER)
    info["n_months"] = int(len(long))
    return cov, info


def bond_evidence() -> dict:
    """Starting 10y Bund yield vs realised annualised return of the rolling
    10y par bond over the next 10 years."""
    y = R.bund_yield_10y()
    from .bonds import constant_maturity_returns

    r = constant_maturity_returns(y, 10.0)
    idx = (1 + r).cumprod()
    fwd = (idx.shift(-120) / idx) ** (1 / 10) - 1
    df = pd.concat([y.rename("y"), fwd.rename("fwd")], axis=1).dropna()
    b = np.polyfit(df["y"] / 100, df["fwd"], 1)
    pred = b[0] * df["y"] / 100 + b[1]
    r2 = 1 - ((df["fwd"] - pred) ** 2).sum() / ((df["fwd"] - df["fwd"].mean()) ** 2).sum()
    pts = df.iloc[::3]
    return {
        "points": [[p.strftime("%Y-%m"), r4(v.y / 100), r4(v.fwd)] for p, v in pts.iterrows()],
        "slope": r4(b[0]),
        "intercept": r4(b[1]),
        "r2": r4(r2, 3),
        "mae": r4(float((df["fwd"] - df["y"] / 100).abs().mean())),
        "sample": [df.index[0].strftime("%Y-%m"), df.index[-1].strftime("%Y-%m")],
    }


def gold_context() -> dict:
    g = R.gold_usd()
    fx = R.usd_per_eur()
    cpi = R.german_cpi()
    df = pd.concat([g / fx, cpi], axis=1, keys=["g", "cpi"]).dropna().loc["1975":]
    real = df["g"] / df["cpi"]
    pct = float((real <= real.iloc[-1]).mean())
    return {
        "real_index": [[d.strftime("%Y-%m"), r4(v / real.iloc[-1], 3)] for d, v in real.iloc[::3].items()],
        "percentile": r4(pct, 3),
        "last": real.index[-1].strftime("%Y-%m"),
        "ratio_to_median": r4(float(real.iloc[-1] / real.median()), 2),
    }


def validation(raw: pd.DataFrame) -> list:
    """Compare the constructed EUR series with investable ETFs over their
    common history. Early months of some Yahoo ETF histories contain data
    errors, so each check starts after the listing settled."""
    fx = R.usd_per_eur()
    checks = [
        ("eq_eu", "iShares STOXX Europe 600 (EXSA)", R.monthly_returns(R.yahoo_monthly("EXSA.DE")).loc["2008":]),
        ("eq_us", "iShares Core S&P 500 in EUR (SXR8)", R.monthly_returns(R.yahoo_monthly("SXR8.DE")).loc["2011":]),
        ("eq_em", "iShares MSCI EM (EEM), in EUR umgerechnet", R.to_eur(em_usd_from_yahoo(), fx).loc["2004":]),
        ("bund", "iShares eb.rexx Government Germany (EUNH)", R.monthly_returns(R.yahoo_monthly("EUNH.DE")).loc["2010":]),
    ]
    out = []
    for k, label, etf in checks:
        j = pd.concat([raw[k], etf], axis=1).dropna()
        geo = (1 + j).prod() ** (12 / len(j)) - 1
        out.append({
            "key": k, "etf": label, "months": int(len(j)),
            "from": j.index[0].strftime("%Y-%m"), "to": j.index[-1].strftime("%Y-%m"),
            "corr": r4(j.corr().iloc[0, 1], 3),
            "geo_model": r4(geo.iloc[0]), "geo_etf": r4(geo.iloc[1]),
        })
    return out


def em_usd_from_yahoo() -> pd.Series:
    y = pd.read_csv(ROOT / "data" / "raw" / "yahoo_monthly.csv", parse_dates=["date"])
    d = y[y["ticker"] == "EEM"].copy()
    d["m"] = d["date"].dt.to_period("M")
    d = d.drop_duplicates("m").set_index("m")["adjclose"]
    d = d[d.index < R.current_month()]
    d.index = d.index.to_timestamp(how="end").normalize()
    return R.monthly_returns(d)


def signal_block(inputs: dict, rets: pd.DataFrame, rc: pd.Series, shiller: pd.DataFrame) -> dict:
    yc = R.ecb_series("ecb_yc_aaa.csv", "SR_5Y")
    aaa5 = float(yc.iloc[-1]) / 100
    gold_pct = gold_context()["percentile"]
    val = SG.valuation_scores(inputs, inputs["eq_em"]["cape"], aaa5, gold_pct)
    tr_all = SG.trend_score(rets[ORDER])
    lr = np.log1p(rets[ORDER])
    ex12 = lr.rolling(12).sum().sub(lr["cash"].rolling(12).sum(), axis=0)
    tr = tr_all.iloc[-1]
    out = {"as_of": rets.index[-1].strftime("%Y-%m"), "aaa5": r4(aaa5), "corr_now": r4(float(rc.iloc[-1]), 3),
           "classes": {}, "backtest": SG.backtest(rets, ORDER), "ref": SG.REF, "tilt": SG.TILT,
           "variants": SG.backtest_combined(rets, ORDER, shiller)}
    for k in ORDER:
        v = val[k]
        out["classes"][k] = {
            "val": r4(v["score"], 3), "trend": r4(float(tr[k]), 3),
            "ex12": r4(float(ex12[k].iloc[-1])),
            # tactical score = trend only; valuation enters the strategic
            # weights through the expected returns (see backtest_combined)
            "score": r4(float(tr[k]), 3),
            "detail": {kk: (r4(x) if isinstance(x, float) else x) for kk, x in v.items() if kk != "score"},
        }
    return out


def as_of(inputs: dict) -> str:
    try:
        return json.loads((ROOT / "data" / "raw" / "fetch_log.json").read_text())["fetched"]
    except FileNotFoundError:
        return inputs["as_of"]


def main() -> None:
    base = json.loads((ROOT / "config" / "inputs.json").read_text())
    inputs, live = live_inputs(base)

    sh = pd.read_csv(ROOT / "data" / "raw" / "shiller.csv", parse_dates=["Date"]).set_index("Date")
    sh.index = sh.index + pd.offsets.MonthEnd(0)
    sh = sh.replace(0.0, np.nan)
    fit = fit_cape_regression(sh, start="1881-01-01", oos_start="1950-01-01")

    cma = build_cma(inputs, fit)

    raw, meta = R.build_returns()
    credit_obs = raw["credit"].dropna()
    end = raw[LONG].dropna().index[-1]
    rets = raw.loc[SAMPLE_START:end].copy()
    credit_filled, bf = R.backfill_credit(raw, SAMPLE_START)
    rets["credit"] = credit_filled.loc[rets.index]
    assert not rets[ORDER].isna().any().any(), rets.isna().sum()

    cov_all, info_all = cov_block(rets, credit_obs)
    rc = rolling_stock_bond_corr(rets["eq_eu"], rets["bund"], 36)
    pos = rc[rc > 0].index
    neg = rc[rc <= 0].index
    cov_pos, info_pos = cov_block(rets, credit_obs, pos)
    cov_neg, info_neg = cov_block(rets, credit_obs, neg)

    # modified duration of the 10y par bond at today's yield (for rate shocks)
    y0 = inputs["bund"]["yield"]
    p_up = par_bond_price(np.array([y0]), np.array([y0 + 0.0001]), 10.0)[0]
    p_dn = par_bond_price(np.array([y0]), np.array([y0 - 0.0001]), 10.0)[0]
    mod_dur = float((p_dn - p_up) / (2 * 100 * 0.0001))

    stress = []
    for name, a, b in STRESS:
        w = rets.loc[a:b, ORDER]
        cum = (1 + w).prod() - 1
        stress.append({
            "name": name,
            "from": a,
            "to": b,
            "months": int(len(w)),
            "returns": {k: r4(cum[k]) for k in ORDER},
            "credit_reconstructed": bool(pd.Timestamp(a) < credit_obs.index[0]),
        })

    cape_pts = fit.scatter.iloc[::3]
    cape_pts = [[d.strftime("%Y-%m"), r4(1 / e, 2), r4(f)] for d, e, f in cape_pts[["Date" if "Date" in cape_pts else "date", "ey", "fwd"]].itertuples(index=False)]

    hist_start = rets.index[0]
    model = {
        "meta": {
            "title": "Strategische Allokation für den Euro-Anleger",
            "author": "Philip Kroos",
            "as_of": as_of(inputs),
            "live": live,
            "anchors": inputs["anchors"],
            "built": date.today().isoformat(),
            "sample": [rets.index[0].strftime("%Y-%m"), rets.index[-1].strftime("%Y-%m")],
            "inflation": inputs["inflation_eur"],
            "credit_observed_from": credit_obs.index[0].strftime("%Y-%m"),
            "credit_backfill": bf,
            "gold_eom_from": R.monthly_returns(R.yahoo_monthly("GC=F")).index[0].strftime("%Y-%m"),
            "bund_mod_duration": r4(mod_dur, 2),
        },
        "assets": [
            {
                "key": k,
                "name": NAMES[k],
                "expected": r4(cma[k]["expected"]),
                "real": r4(cma[k]["real"]),
                "band": [r4(x) for x in cma[k]["band"]],
                "vol": r4(np.sqrt(cov_all.loc[k, k])),
                "hist_geo": r4((1 + rets[k]).prod() ** (12 / len(rets)) - 1),
                "hist_vol": r4(rets[k].std() * np.sqrt(12)),
                "blocks": [{"label": x["label"], "value": r4(x["value"])} for x in cma[k]["blocks"]],
                "detail": {kk: (r4(v) if isinstance(v, float) else v) for kk, v in cma[k]["detail"].items()},
            }
            for k in ORDER
        ],
        "cov": {
            "all": np.round(cov_all.values, 6).tolist(),
            "pos": np.round(cov_pos.values, 6).tolist(),
            "neg": np.round(cov_neg.values, 6).tolist(),
            "info": {"all": info_all, "pos": info_pos, "neg": info_neg},
        },
        "cape": {
            "alpha": r4(fit.alpha),
            "beta": r4(fit.beta),
            "se_alpha": r4(fit.se_alpha),
            "se_beta": r4(fit.se_beta),
            "r2": r4(fit.r2, 3),
            "oos_r2": r4(fit.oos_r2, 3),
            "oos_start": fit.oos_start,
            "resid_sd": r4(fit.resid_sd),
            "n_obs": fit.n_obs,
            "n_indep": r4(fit.n_indep, 1),
            "sample": fit.sample,
            "points": cape_pts,
            "current": {k: r4(inputs[k]["cape"], 2) for k in ("eq_us", "eq_eu", "eq_em")},
        },
        "bonds": bond_evidence(),
        "gold": gold_context(),
        "stock_bond_corr": [[d.strftime("%Y-%m"), r4(v, 3)] for d, v in rc.items()],
        "stress": stress,
        "signals": signal_block(inputs, rets, rc, sh),
        "validation": validation(raw),
        "history": {
            "start": hist_start.strftime("%Y-%m"),
            "returns": {k: [r4(x, 5) for x in rets[k].values] for k in ORDER},
            "credit_reconstructed_until": (credit_obs.index[0] - pd.offsets.MonthEnd(1)).strftime("%Y-%m"),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
