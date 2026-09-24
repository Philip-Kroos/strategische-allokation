"""Monthly total returns in EUR for the seven asset classes.

All series end up as simple monthly returns (decimal) indexed at month end.
Foreign-currency assets are unhedged: the EUR return combines the local
return with the change of the EUR/USD rate. Before 1999 the euro is the
Deutsche Mark at the irrevocable conversion rate of 1.95583 DEM per EUR.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .bonds import constant_maturity_returns

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
DEM_PER_EUR = 1.95583

ASSETS = [
    ("cash", "Geldmarkt EUR"),
    ("bund", "Bundesanleihen 10 J."),
    ("credit", "Unternehmensanleihen EUR (IG)"),
    ("eq_eu", "Aktien Europa"),
    ("eq_us", "Aktien USA"),
    ("eq_em", "Aktien Schwellenländer"),
    ("gold", "Gold"),
]


BRIDGE = {"eq_eu": ["EXSA.DE"], "eq_us": ["SXR8.DE"], "eq_em": ["IEMM.AS", "EEM"]}


def _me(idx) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(idx) + pd.offsets.MonthEnd(0)


def fred_bundle() -> pd.DataFrame:
    f = pd.read_csv(RAW / "fred_bundle.csv", parse_dates=["observation_date"]).set_index("observation_date")
    f.index = _me(f.index)
    return f


def ecb_series(fname: str, key_filter: str | None = None) -> pd.Series:
    df = pd.read_csv(RAW / fname, usecols=lambda c: c in ("KEY", "TIME_PERIOD", "OBS_VALUE"))
    if key_filter:
        df = df[df["KEY"].str.contains(key_filter, regex=False)]
    s = pd.Series(df["OBS_VALUE"].astype(float).values, index=pd.to_datetime(df["TIME_PERIOD"]))
    return s.dropna().sort_index()


def french(zip_name: str) -> pd.Series:
    """Total market return (Mkt-RF + RF) in USD, decimal, month end."""
    with zipfile.ZipFile(RAW / zip_name) as z:
        raw = z.read(z.namelist()[0]).decode("latin-1")
    lines = raw.splitlines()
    start = next(i for i, l in enumerate(lines) if "Mkt-RF" in l)
    header = [h.strip() for h in lines[start].split(",")]
    rows = []
    for l in lines[start + 1:]:
        p = [x.strip() for x in l.split(",")]
        if not p[0].isdigit() or len(p[0]) != 6:
            break
        rows.append(p)
    df = pd.DataFrame(rows, columns=["yyyymm"] + header[1:]).set_index("yyyymm").astype(float)
    df = df.replace(-99.99, np.nan)
    df.index = pd.to_datetime(df.index, format="%Y%m") + pd.offsets.MonthEnd(0)
    return ((df["Mkt-RF"] + df["RF"]) / 100.0).dropna()


def usd_per_eur() -> pd.Series:
    f = fred_bundle()
    pre = DEM_PER_EUR / f["EXGEUS"].dropna()          # monthly average, DEM per USD
    post = ecb_series("ecb_eurusd.csv")                # end of period, USD per EUR
    post.index = _me(post.index)
    fx = pd.concat([pre[pre.index < "1999-01-01"], post]).sort_index()
    return fx[~fx.index.duplicated(keep="last")]


def to_eur(r_usd: pd.Series, fx: pd.Series) -> pd.Series:
    fx_ret = fx.shift(1) / fx - 1.0      # EUR investor: USD appreciation is a gain
    df = pd.concat([r_usd, fx_ret], axis=1, keys=["r", "fx"]).dropna()
    return (1 + df["r"]) * (1 + df["fx"]) - 1


def bund_yield_10y() -> pd.Series:
    """Month-end 10-year yield on Federal securities (Bundesbank, Svensson
    term structure, since 1972-09). Month-end values matter: monthly
    averages lag month-end equity prices and bias the stock-bond correlation
    towards zero."""
    lines = (RAW / "bbk_zst_10y.csv").read_text(encoding="utf-8-sig").splitlines()
    rows = [l.split(",") for l in lines if re.match(r"^\d{4}-\d{2},", l)]
    idx = pd.PeriodIndex([r[0] for r in rows], freq="M").to_timestamp(how="end").normalize()
    vals = pd.to_numeric(pd.Series([r[1] for r in rows]), errors="coerce").values
    return pd.Series(vals, index=idx, name="bund10").dropna()


def german_cpi() -> pd.Series:
    f = fred_bundle()
    old = f["DEUCPIALLMINMEI"].dropna()
    new = f["CP0000DEM086NEST"].dropna()
    # splice: chain HICP-DE growth onto national CPI after the overlap
    ratio = (old / new).dropna().loc["2020":].mean()
    spliced = pd.concat([old, new.loc[new.index > old.index[-1]] * ratio]).sort_index()
    # months FRED has not yet published: chain the ECB HICP for Germany
    try:
        ecb = ecb_series("ecb_hicp.csv", "ICP.M.DE.")
        ecb.index = _me(ecb.index)
        ext = ecb[ecb.index > spliced.index[-1]]
        if len(ext) and spliced.index[-1] in ecb.index:
            spliced = pd.concat([spliced, spliced.iloc[-1] * ext / ecb.loc[spliced.index[-1]]])
    except (FileNotFoundError, KeyError):
        pass
    return spliced


def yahoo_monthly(ticker: str) -> pd.Series:
    """Month-end adjusted closes from the Yahoo chart API export.

    Yahoo stamps monthly bars at the start of the bar in UTC. For European
    listings that stamp falls on the last day of the previous month, so dates
    from the 25th onward belong to the following month. The live quote and the
    running month are dropped."""
    df = pd.read_csv(RAW / "yahoo_monthly.csv", parse_dates=["date"])
    df = df[df["ticker"] == ticker].copy()
    per = df["date"].dt.to_period("M")
    per = per.where(df["date"].dt.day < 25, per + 1)
    df["m"] = per
    df = df.drop_duplicates("m", keep="first").set_index("m")["adjclose"].astype(float)
    df = df[df.index < current_month()]
    s = df.copy()
    s.index = s.index.to_timestamp(how="end").normalize()
    return s.rename(ticker)


def current_month() -> pd.Period:
    """The running month, whose bar is still incomplete."""
    try:
        log = json.loads((RAW / "fetch_log.json").read_text())
        return pd.Period(log["fetched"][:7], "M")
    except (FileNotFoundError, KeyError):
        return pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("M")


def monthly_returns(level: pd.Series) -> pd.Series:
    """Simple returns between consecutive calendar months only; gaps give NaN."""
    full = level.resample("ME").last()
    return (full / full.shift(1) - 1).dropna()


def gold_usd() -> pd.Series:
    df = pd.read_csv(RAW / "gold_monthly.csv")
    return pd.Series(df["Price"].astype(float).values, index=_me(pd.to_datetime(df["Date"])), name="gold")


def build_returns() -> tuple[pd.DataFrame, dict]:
    f = fred_bundle()
    fx = usd_per_eur()

    rate = f["IR3TIB01DEM156N"].dropna()
    # months FRED has not yet published: three-month Euribor (ECB)
    try:
        eur = ecb_series("ecb_euribor3m.csv")
        eur.index = _me(eur.index)
        rate = pd.concat([rate, eur[eur.index > rate.index[-1]]])
    except FileNotFoundError:
        pass
    cash = (rate.shift(1) / 100.0 / 12.0).dropna().rename("cash")
    bund = constant_maturity_returns(bund_yield_10y(), 10.0).rename("bund")

    eq_us = to_eur(french("F-F_Research_Data_Factors_CSV.zip"), fx).rename("eq_us")
    eq_eu = to_eur(french("Europe_3_Factors_CSV.zip"), fx).rename("eq_eu")
    eq_em = to_eur(french("Emerging_5_Factors_CSV.zip"), fx).rename("eq_em")
    # Gold: month-end COMEX front-month settlement from Nov 2000 (Yahoo GC=F).
    # Before that only the World Bank monthly average exists; averaging smooths
    # volatility and lags, so it is used only where nothing else is available.
    # Months missing in the Yahoo history are filled with the geometric mean
    # of the World Bank averages of that month and the next, a proxy for the
    # month-end level.
    avg = gold_usd()
    eom = yahoo_monthly("GC=F").resample("ME").last()
    proxy = np.sqrt(avg * avg.shift(-1))
    eom = eom.fillna(proxy.reindex(eom.index))
    g_eom = (eom / eom.shift(1) - 1).dropna()
    g_avg = avg.pct_change().dropna()
    g_usd = pd.concat([g_avg[g_avg.index < g_eom.index[0]], g_eom]).sort_index()
    gold = to_eur(g_usd, fx).rename("gold")

    credit_obs = monthly_returns(yahoo_monthly("IEAC.L")).rename("credit")

    # The French library publishes with a lag of one to two months. Until it
    # catches up, the missing months come from EUR-listed index ETFs
    # (monthly correlation with the index series 0.97 to 0.99 since 2012).
    # Next month the index data replace the bridge.
    bridge = {}
    eq = {"eq_eu": eq_eu, "eq_us": eq_us, "eq_em": eq_em}
    for k, tickers in BRIDGE.items():
        for t in tickers:
            try:
                p = monthly_returns(yahoo_monthly(t))
            except (FileNotFoundError, KeyError, IndexError):
                continue
            if p.empty:
                continue
            if t == "EEM":
                p = to_eur(p, fx)
            new = p[p.index > eq[k].index[-1]]
            if len(new):
                eq[k] = pd.concat([eq[k], new.rename(k)])
                bridge[k] = {"ticker": t, "months": [d.strftime("%Y-%m") for d in new.index]}
            break
    eq_eu, eq_us, eq_em = eq["eq_eu"], eq["eq_us"], eq["eq_em"]

    df = pd.concat([cash, bund, credit_obs, eq_eu, eq_us, eq_em, gold], axis=1)
    meta = {"credit_observed_from": credit_obs.index[0].strftime("%Y-%m"), "equity_bridge": bridge}
    return df, meta


def backfill_credit(df: pd.DataFrame, start: str) -> tuple[pd.Series, dict]:
    """Reconstruct credit returns before the ETF history by projecting on the
    long-history assets (Stambaugh 1997). Returns fitted values before the
    observed history and the observed series afterwards."""
    X_cols = ["cash", "bund", "eq_eu"]
    obs = df[["credit"] + X_cols].dropna()
    X = np.column_stack([np.ones(len(obs)), obs[X_cols].values])
    beta, *_ = np.linalg.lstsq(X, obs["credit"].values, rcond=None)
    fitted_all = beta[0] + df[X_cols].values @ beta[1:]
    fitted = pd.Series(fitted_all, index=df.index)
    resid = obs["credit"].values - X @ beta
    r2 = 1 - resid.var() / obs["credit"].var()
    out = df["credit"].copy()
    mask = out.isna() & fitted.notna() & (df.index >= start)
    out[mask] = fitted[mask]
    info = {
        "beta": dict(zip(["const"] + X_cols, [float(b) for b in beta])),
        "r2": float(r2),
        "resid_sd_monthly": float(resid.std(ddof=len(beta))),
        "overlap": [obs.index[0].strftime("%Y-%m"), obs.index[-1].strftime("%Y-%m")],
    }
    return out, info
