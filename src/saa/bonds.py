"""Total returns of constant-maturity bonds from yield series.

A bond that is bought at par at the end of month t-1 (coupon = yield y_{t-1},
maturity M years) is valued one month later at yield y_t with remaining
maturity M - 1/12. The monthly total return is price change plus accrued
coupon. This is the standard construction for long government bond return
histories (e.g. Swinkels 2019, Data in Brief), and it avoids the second-order
error of a duration-only approximation when yields move a lot.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def par_bond_price(coupon: np.ndarray, yld: np.ndarray, maturity: float, freq: int = 1) -> np.ndarray:
    """Clean price (per 100 nominal) of a bond with annual coupon `coupon` (decimal),
    discounted at `yld` (decimal, same compounding), `maturity` in years.
    Fractional periods are handled by discounting on a continuous time grid."""
    coupon = np.asarray(coupon, dtype=float)
    yld = np.asarray(yld, dtype=float)
    n_full = int(np.floor(maturity * freq))
    stub = maturity * freq - n_full
    # coupon dates measured in periods from today: stub, stub+1, ..., stub+n_full
    times = stub + np.arange(0, n_full + 1)
    times = times[times > 1e-9]
    disc = (1.0 + yld[..., None] / freq) ** (-times)
    cpn = 100.0 * coupon[..., None] / freq
    price = (cpn * disc).sum(axis=-1) + 100.0 * disc[..., -1]
    # remove accrued interest so the result is a clean price
    accrued = 100.0 * coupon / freq * (1.0 - stub) if stub > 1e-9 else 0.0
    return price - accrued


def constant_maturity_returns(yields: pd.Series, maturity: float = 10.0) -> pd.Series:
    """Monthly total return (decimal) of a rolling par bond.

    `yields` is a monthly series in percent. The first observation is lost."""
    y = yields.astype(float) / 100.0
    y_prev = y.shift(1)
    price_now = par_bond_price(y_prev.values, y.values, maturity - 1.0 / 12.0)
    carry = y_prev.values / 12.0
    ret = (price_now - 100.0) / 100.0 + carry
    out = pd.Series(ret, index=yields.index, name=yields.name)
    return out.iloc[1:]


def credit_returns(yields: pd.Series, maturity: float, annual_loss: float) -> pd.Series:
    """Rolling par bond on a credit yield index, net of expected default and
    downgrade losses (`annual_loss`, decimal p.a.). Losses are deducted evenly
    because monthly realised defaults are not observed in a yield index."""
    r = constant_maturity_returns(yields, maturity)
    return r - annual_loss / 12.0
