"""Covariance estimation.

- Ledoit-Wolf (2003) shrinkage towards the constant-correlation target.
- Short histories (euro credit ETF since 2009) enter through the Stambaugh
  (1997) projection: regress the short series on the long ones over the
  overlap, then combine the coefficients with the full-sample covariance of
  the long series. This uses all 36 years for the long assets instead of
  truncating everything to the shortest history.
- Regime covariances split the sample by the sign of the rolling 36-month
  correlation between European equities and Bunds.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ledoit_wolf_cc(X: np.ndarray) -> tuple[np.ndarray, float]:
    """Shrink the sample covariance of X (T x N, demeaned inside) towards the
    constant-correlation matrix. Returns (Sigma, shrinkage intensity)."""
    T, N = X.shape
    Xc = X - X.mean(axis=0)
    S = Xc.T @ Xc / T
    sd = np.sqrt(np.diag(S))
    R = S / np.outer(sd, sd)
    rbar = (R.sum() - N) / (N * (N - 1))
    F = rbar * np.outer(sd, sd)
    np.fill_diagonal(F, np.diag(S))

    # pi: sum of asymptotic variances of the sample covariances
    Y = Xc ** 2
    pi_mat = (Y.T @ Y) / T - S ** 2
    pi_hat = pi_mat.sum()
    # rho: asymptotic covariances between target and sample entries
    term1 = ((Xc ** 3).T @ Xc) / T
    help_ = np.diag(S)[:, None] * S
    theta = term1 - help_
    np.fill_diagonal(theta, 0.0)
    rho_diag = np.diag(pi_mat).sum()
    rho_off = rbar * ((np.outer(1 / sd, sd)) * theta).sum()
    rho_hat = rho_diag + rho_off
    gamma = np.linalg.norm(S - F, "fro") ** 2
    kappa = (pi_hat - rho_hat) / gamma
    delta = float(max(0.0, min(1.0, kappa / T)))
    return delta * F + (1 - delta) * S, delta


def stambaugh_cov(long: pd.DataFrame, short: pd.Series, shrink: bool = True) -> tuple[pd.DataFrame, dict]:
    """Annualised covariance of [long assets..., short asset]."""
    Sll, delta = ledoit_wolf_cc(long.values) if shrink else (np.cov(long.values.T, ddof=1), 0.0)
    ov = pd.concat([short, long], axis=1).dropna()
    y = ov.iloc[:, 0].values
    X = np.column_stack([np.ones(len(ov)), ov.iloc[:, 1:].values])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ b
    s2e = resid.var(ddof=X.shape[1])
    B = b[1:]
    cov_sl = Sll @ B
    var_s = B @ Sll @ B + s2e
    N = Sll.shape[0]
    full = np.zeros((N + 1, N + 1))
    full[:N, :N] = Sll
    full[N, :N] = full[:N, N] = cov_sl
    full[N, N] = var_s
    names = list(long.columns) + [short.name]
    info = {"shrinkage": delta, "r2": float(1 - resid.var() / y.var()), "n_overlap": int(len(ov))}
    return pd.DataFrame(full * 12.0, index=names, columns=names), info


def rolling_stock_bond_corr(eq: pd.Series, bond: pd.Series, window: int = 36) -> pd.Series:
    return eq.rolling(window).corr(bond).dropna()


def nearest_psd(A: np.ndarray) -> np.ndarray:
    w, V = np.linalg.eigh((A + A.T) / 2)
    w = np.clip(w, 1e-10, None)
    return V @ np.diag(w) @ V.T
