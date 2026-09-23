"""Capital market assumptions: 10-year expected returns in EUR.

Every number here is either read from data or is a stated, sourced input in
config/inputs.json. Nothing is tuned to produce a particular portfolio.

Conventions
- Returns are geometric (compound) annual returns over 10 years, nominal EUR.
- Foreign equities are unhedged. Under relative PPP the expected currency
  move offsets the inflation differential, so the EUR return of a foreign
  market is its real local return plus euro-area inflation.
"""
from __future__ import annotations

import numpy as np

from .valuation import CapeFit


def gk_real(dy: float, nb: float, g: float, cape: float, cape_fair: float, closure: float, horizon: int = 10) -> tuple[float, float]:
    """Grinold-Kroner (2002) real return:
        dividend yield + net buyback yield (minus dilution) + real growth of
        aggregate earnings + change in valuation.
    Repricing assumes that `closure` of the gap between current and fair
    CAPE closes over the horizon. Returns (total, repricing component)."""
    target = cape + closure * (cape_fair - cape)
    reprice = (target / cape) ** (1.0 / horizon) - 1.0
    return dy + nb + g + reprice, reprice


def equity_cma(inp: dict, fit: CapeFit, infl: float) -> dict:
    cape = inp["cape"]
    m1 = fit.predict(cape)
    m2, reprice = gk_real(inp["dy"], inp["net_buyback"], inp["g_real"], cape, inp["cape_fair"], inp["closure"])
    real = 0.5 * (m1 + m2)
    nominal = (1 + real) * (1 + infl) - 1
    sd = fit.resid_sd
    return {
        "expected": nominal,
        "real": real,
        "band": [nominal - sd, nominal + sd],
        "blocks": [
            {"label": "Real, CAPE-Regression", "value": m1},
            {"label": "Real, Bausteine", "value": m2},
            {"label": "Inflation EUR", "value": nominal - real},
        ],
        "detail": {
            "cape": cape,
            "cape_source": inp["cape_source"],
            "m1_regression_real": m1,
            "m2_building_blocks_real": m2,
            "dy": inp["dy"],
            "dy_source": inp["dy_source"],
            "g_real": inp["g_real"],
            "net_buyback": inp["net_buyback"],
            "buyback_source": inp["buyback_source"],
            "g_source": inp["g_source"],
            "fair_source": inp["fair_source"],
            "cape_fair": inp["cape_fair"],
            "closure": inp["closure"],
            "reprice": reprice,
        },
    }


def build_cma(inputs: dict, fit: CapeFit) -> dict:
    infl = inputs["inflation_eur"]["value"]
    out = {}

    c = inputs["cash"]
    out["cash"] = {
        "expected": c["value"],
        "real": (1 + c["value"]) / (1 + infl) - 1,
        "band": [c["value"] - c["band"], c["value"] + c["band"]],
        "blocks": [{"label": "Erwarteter Geldmarktsatz", "value": c["value"]}],
        "detail": c,
    }

    b = inputs["bund"]
    out["bund"] = {
        "expected": b["yield"],
        "real": (1 + b["yield"]) / (1 + infl) - 1,
        "band": [b["yield"] - b["band"], b["yield"] + b["band"]],
        "blocks": [{"label": "Startrendite", "value": b["yield"]}],
        "detail": b,
    }

    cr = inputs["credit"]
    e = cr["ytm"] - cr["loss"]
    out["credit"] = {
        "expected": e,
        "real": (1 + e) / (1 + infl) - 1,
        "band": [e - cr["band"], e + cr["band"]],
        "blocks": [
            {"label": "Rendite auf Verfall", "value": cr["ytm"]},
            {"label": "Ausfall- und Herabstufungsverluste", "value": -cr["loss"]},
        ],
        "detail": cr,
    }

    for k in ("eq_eu", "eq_us", "eq_em"):
        out[k] = equity_cma(inputs[k], fit, infl)

    g = inputs["gold"]
    gn = (1 + g["real"]) * (1 + infl) - 1
    out["gold"] = {
        "expected": gn,
        "real": g["real"],
        "band": [gn - g["band"], gn + g["band"]],
        "blocks": [
            {"label": "Inflation EUR", "value": gn - g["real"]},
            {"label": "Realer Preistrend", "value": g["real"]},
        ],
        "detail": g,
    }
    return out
