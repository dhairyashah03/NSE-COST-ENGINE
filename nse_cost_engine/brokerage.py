"""
Brokerage calculator.

Supports five brokerage models:
    zero       — ₹0 (common for delivery at discount brokers)
    flat       — fixed ₹ per executed order (e.g. ₹20)
    percentage — % of trade value
    min_of     — min(flat, percentage × value) — Zerodha / Dhan model
    slab       — different rates for different turnover bands (full‑service brokers)

The model is determined by the broker profile YAML, not by this code.
"""

from __future__ import annotations

from typing import Dict, Any, List

from nse_cost_engine.models import Trade, Segment
from nse_cost_engine.utils import segment_key, get_turnover_base


def calculate_brokerage(trade: Trade, config: Dict[str, Any]) -> float:
    """
    Calculate brokerage for a single trade leg.

    Parameters
    ----------
    trade : Trade
    config : dict
        Full merged config (default_rates + broker profile).

    Returns
    -------
    float
        Brokerage amount in ₹.
    """
    brokerage_config = config.get("brokerage", {})

    # Determine which sub‑config to use
    key = _brokerage_key(trade)
    model_config = brokerage_config.get(key, {})

    if not model_config:
        return 0.0

    model = model_config.get("model", "zero")
    value = get_turnover_base(trade)

    if model == "zero":
        return 0.0

    elif model == "flat":
        return float(model_config.get("rate", 0))

    elif model == "percentage":
        rate = float(model_config.get("rate", 0))
        return value * rate

    elif model == "min_of":
        flat = float(model_config.get("flat", 0))
        pct = float(model_config.get("percentage", 0))
        return min(flat, value * pct)

    elif model == "slab":
        return _calculate_slab(value, model_config.get("slabs", []))

    else:
        raise ValueError(f"Unknown brokerage model: '{model}'")


def _brokerage_key(trade: Trade) -> str:
    """
    Map a trade to its brokerage config key.

    Options and futures don't have delivery/intraday distinction
    in brokerage — they're just 'options' and 'futures'.
    Equity and ETF need the trade_type qualifier.
    """
    seg = trade.segment.value

    if seg in ("futures", "options"):
        return seg

    from nse_cost_engine.models import TradeType
    tt = trade.trade_type
    if tt == TradeType.MTF:
        # MTF brokerage — check if broker has a specific MTF rate,
        # otherwise fall back to delivery
        # Most discount brokers charge intraday-style brokerage on MTF
        tt = TradeType.INTRADAY

    return f"{seg}_{tt.value}"


def _calculate_slab(value: float, slabs: List[Dict]) -> float:
    """
    Slab‑based brokerage (full‑service brokers).

    slabs is a list of: {upper_limit: float|null, rate: float}
    sorted by upper_limit ascending.
    """
    for slab in slabs:
        upper = slab.get("upper_limit")
        if upper is None or value <= upper:
            return value * float(slab.get("rate", 0))
    # If value exceeds all slabs, use the last slab's rate
    if slabs:
        return value * float(slabs[-1].get("rate", 0))
    return 0.0