"""Valuation and long-horizon equity returns.

The cyclically adjusted earnings yield (1/CAPE) is the best documented single
predictor of 10-year real equity returns (Campbell & Shiller 1998; Asness,
Ilmanen & Maloney 2017). We estimate the relation on the long US sample and
apply it to each region's current CAPE.

Two statistical points matter and are handled explicitly:
1. Overlapping 10-year windows make residuals strongly autocorrelated.
   Standard errors are Newey-West with 120 lags.
2. In-sample fit overstates forecast power. We therefore also report an
   expanding-window out-of-sample R^2 against the historical mean
   (Goyal & Welch 2008; Campbell & Thompson 2008).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

HORIZON = 120  # months


def real_total_return_index(sh: pd.DataFrame) -> pd.Series:
    """Real total return index of the S&P Composite from Shiller's monthly file."""
    p = sh["SP500"]
    d = sh["Dividend"]
    cpi = sh["Consumer Price Index"]
    df = pd.concat([p, d, cpi], axis=1, keys=["p", "d", "cpi"]).dropna()
    gross = (df["p"] + df["d"] / 12.0) / df["p"].shift(1)
    infl = df["cpi"] / df["cpi"].shift(1)
    real = (gross / infl).dropna()
    return real.cumprod().rename("sp_real_tr")


@dataclass
class CapeFit:
    alpha: float
    beta: float
    se_alpha: float
    se_beta: float
    r2: float
    resid_sd: float
    n_obs: int
    n_indep: float
    sample: tuple[str, str]
    oos_r2: float
    oos_start: str
    scatter: pd.DataFrame  # columns: date, ey, fwd

    def predict(self, cape: float) -> float:
        return self.alpha + self.beta / cape

    def predict_sd(self, cape: float) -> float:
        """Forecast standard deviation for a single 10y outcome (parameter
        uncertainty is small relative to residual dispersion; residual SD is
        the relevant measure of how wrong a single decade can be)."""
        return self.resid_sd


def fit_cape_regression(sh: pd.DataFrame, start: str = "1900-01-01", oos_start: str = "1950-01-01") -> CapeFit:
    tri = real_total_return_index(sh)
    fwd = (tri.shift(-HORIZON) / tri) ** (12.0 / HORIZON) - 1.0
    ey = 1.0 / sh["PE10"]
    df = pd.concat([ey.rename("ey"), fwd.rename("fwd")], axis=1).dropna()
    df = df.loc[start:]
    X = sm.add_constant(df["ey"])
    res = sm.OLS(df["fwd"], X).fit(cov_type="HAC", cov_kwds={"maxlags": HORIZON})

    # expanding-window out-of-sample test: at date t only windows that have
    # fully ended by t can be used for estimation.
    preds, bench, actual = [], [], []
    dates = df.loc[oos_start:].index
    for t in dates[::3]:  # quarterly steps are enough and keep it fast
        cutoff = t - pd.DateOffset(months=HORIZON)
        train = df.loc[:cutoff]
        if len(train) < 240:
            continue
        b = np.polyfit(train["ey"], train["fwd"], 1)
        preds.append(b[0] * df.at[t, "ey"] + b[1])
        bench.append(train["fwd"].mean())
        actual.append(df.at[t, "fwd"])
    preds, bench, actual = map(np.asarray, (preds, bench, actual))
    oos_r2 = 1.0 - np.sum((actual - preds) ** 2) / np.sum((actual - bench) ** 2)

    scatter = df.reset_index().rename(columns={"index": "date", "Date": "date"})
    return CapeFit(
        alpha=float(res.params["const"]),
        beta=float(res.params["ey"]),
        se_alpha=float(res.bse["const"]),
        se_beta=float(res.bse["ey"]),
        r2=float(res.rsquared),
        resid_sd=float(np.std(res.resid, ddof=2)),
        n_obs=int(res.nobs),
        n_indep=float(res.nobs) / HORIZON,
        sample=(df.index[0].strftime("%Y-%m"), df.index[-1].strftime("%Y-%m")),
        oos_r2=float(oos_r2),
        oos_start=oos_start[:7],
        scatter=scatter,
    )
