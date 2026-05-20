"""
Market impact models.

These estimate the hidden cost of executing an order — the price
displacement your order causes by consuming liquidity from the book.

Models implemented:
    1. Square‑root model (industry standard):
       impact = σ × √(Q / V) × η

    2. Almgren‑Chriss linear model (stretch goal):
       temporary + permanent impact components

Unlike regulatory charges, market impact is an *estimate*, not a precise
number. The engine returns it separately so consumers can choose whether
to include it in total costs.
"""

from __future__ import annotations

import math
from typing import Dict, Any, Optional

from nse_cost_engine.models import Trade


def calculate_market_impact(
    trade: Trade,
    config: Dict[str, Any],
    model: str = "sqrt",
) -> float:
    """
    Estimate market impact cost.

    Parameters
    ----------
    trade : Trade
        Must have daily_volatility and avg_daily_volume populated.
        If either is None, returns 0.0 (impact not estimable).
    config : dict
        May contain 'market_impact' section with calibration params.
    model : str
        'sqrt' (default) or 'almgren_chriss'.

    Returns
    -------
    float
        Estimated impact cost in ₹.
    """
    if trade.daily_volatility is None or trade.avg_daily_volume is None:
        return 0.0

    if trade.avg_daily_volume <= 0:
        return 0.0

    if model == "sqrt":
        return _sqrt_impact(trade, config)
    elif model == "almgren_chriss":
        return _almgren_chriss_impact(trade, config)
    else:
        raise ValueError(f"Unknown market impact model: '{model}'")


def _sqrt_impact(trade: Trade, config: Dict[str, Any]) -> float:
    """
    Square‑root impact model:
        impact_pct = σ × √(Q / V) × η
        impact_cost = impact_pct × trade_value

    Where:
        σ = daily volatility (annualised vol / √252, or directly provided)
        Q = total order shares (quantity × lot_size)
        V = average daily volume in shares
        η = calibration constant (market‑specific, typically 0.1–0.5)

    The square‑root relationship is empirically well‑established:
    doubling order size increases impact by ~41%, not 100%.
    """
    mi_config = config.get("market_impact", {})
    eta = float(mi_config.get("eta", 0.3))  # default calibration

    sigma = trade.daily_volatility
    order_shares = trade.quantity * trade.lot_size
    adv = trade.avg_daily_volume

    participation = order_shares / adv
    impact_pct = sigma * math.sqrt(participation) * eta
    trade_val = trade.trade_value

    return impact_pct * trade_val


def _almgren_chriss_impact(trade: Trade, config: Dict[str, Any]) -> float:
    """
    Almgren‑Chriss linear impact model (simplified single‑period version).

    Total impact = temporary + permanent

    Temporary: η × σ × (Q / (V × T))
        — price displacement that reverts; proportional to trading rate

    Permanent: γ × σ × (Q / V)
        — information leakage; proportional to total quantity

    Where T = execution time in days (default 1 for immediate execution).

    This is a simplified version — the full Almgren‑Chriss framework
    optimises the execution schedule to minimise total cost. That's
    a Phase 2 extension.
    """
    mi_config = config.get("market_impact", {})
    eta = float(mi_config.get("ac_eta", 0.142))       # temporary impact coefficient
    gamma = float(mi_config.get("ac_gamma", 0.314))    # permanent impact coefficient
    exec_days = float(mi_config.get("ac_exec_days", 1.0))

    sigma = trade.daily_volatility
    order_shares = trade.quantity * trade.lot_size
    adv = trade.avg_daily_volume

    participation = order_shares / adv
    trading_rate = participation / exec_days

    temporary = eta * sigma * trading_rate
    permanent = gamma * sigma * participation

    impact_pct = temporary + permanent
    return impact_pct * trade.trade_value