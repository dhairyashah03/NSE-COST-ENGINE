"""
MTF (Margin Trading Facility) calculator.

Computes:
1. Interest on the funded amount (trade_value × funding_pct) at slab-based
   annual rates, accrued daily. Interest only applies on BUY side.
2. Pledge/unpledge charges: ₹15/transaction/ISIN + 18% GST (Dhan).
   Pledge on buy, unpledge on sell.

Key behaviours (confirmed from Dhan's MTF page):
- Slabs are FLAT by default: entire funded amount at the applicable slab rate.
  Not marginal/incremental like income tax.
- Interest starts T+1 (buy settlement) and ends one day before sell settlement.
- The caller computes mtf_holding_days accounting for holidays; this module
  just does the math.
- Leverage varies per stock (e.g. 4.55× for RELIANCE). User provides leverage,
  engine derives funding_pct = 1 - (1/leverage).
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional, Tuple

from nse_cost_engine.models import Trade, TradeType, Side
from nse_cost_engine.config_loader import get_rate


def calculate_mtf_interest(trade: Trade, config: Dict[str, Any]) -> float:
    """
    Calculate MTF interest for a single trade.

    Interest only accrues on BUY side — you're funding the purchase.
    On sell side, interest is zero (position is being closed).

    Returns 0.0 if:
    - trade_type is not MTF
    - side is SELL
    - mtf_holding_days is None or 0
    """
    if trade.trade_type != TradeType.MTF:
        return 0.0

    # Interest only on buy side
    if trade.side != Side.BUY:
        return 0.0

    if trade.mtf_holding_days is None or trade.mtf_holding_days <= 0:
        return 0.0

    funded = trade.funded_amount
    if funded <= 0:
        return 0.0

    mtf_config = config.get("mtf", {})
    slabs = mtf_config.get("interest_slabs", [])
    slab_type = mtf_config.get("slab_type", "flat")

    if not slabs:
        return 0.0

    if slab_type == "marginal":
        annual_interest = _marginal_interest(funded, slabs)
    else:
        annual_interest = _flat_interest(funded, slabs)

    # Daily accrual
    daily_interest = annual_interest / 365
    return daily_interest * trade.mtf_holding_days


def calculate_mtf_pledge_charges(trade: Trade, config: Dict[str, Any]) -> Tuple[float, float]:
    """
    Calculate MTF pledge/unpledge charges.

    Dhan charges ₹15/transaction/ISIN + 18% GST for:
    - Pledge (on buy — shares pledged to broker as collateral)
    - Unpledge (on sell — shares released back)

    So both buy and sell legs incur one pledge charge each.

    Returns
    -------
    (pledge_charge, pledge_gst) : Tuple[float, float]
    """
    if trade.trade_type != TradeType.MTF:
        return 0.0, 0.0

    mtf_config = config.get("mtf", {})
    pledge_rate = float(mtf_config.get("pledge_charge_per_isin", 15.0))
    gst_rate = get_rate(config, "gst", "rate", default=0.18)

    pledge_gst = pledge_rate * gst_rate
    return pledge_rate, pledge_gst


def _flat_interest(funded: float, slabs: List[Dict]) -> float:
    """
    Flat slab: entire funded amount at the single applicable rate.

    Example (Dhan):
        funded = ₹8,00,000 → falls in slab 2 (₹5L–₹10L) → 13.49% on full ₹8L
    """
    rate = _find_flat_rate(funded, slabs)
    return funded * rate


def _marginal_interest(funded: float, slabs: List[Dict]) -> float:
    """
    Marginal/incremental slab: each band taxed at its own rate.

    Example:
        funded = ₹8,00,000
        First ₹5L at 12.49%, next ₹3L at 13.49%
    """
    interest = 0.0
    remaining = funded
    prev_limit = 0.0

    for slab in slabs:
        upper = slab.get("upper_limit")
        rate = float(slab.get("annual_rate", 0))

        if upper is None:
            interest += remaining * rate
            remaining = 0
            break

        upper = float(upper)
        band_width = upper - prev_limit

        if remaining <= band_width:
            interest += remaining * rate
            remaining = 0
            break
        else:
            interest += band_width * rate
            remaining -= band_width
            prev_limit = upper

    if remaining > 0 and slabs:
        last_rate = float(slabs[-1].get("annual_rate", 0))
        interest += remaining * last_rate

    return interest


def _find_flat_rate(funded: float, slabs: List[Dict]) -> float:
    """Find the applicable flat rate for a given funded amount."""
    for slab in slabs:
        upper = slab.get("upper_limit")
        rate = float(slab.get("annual_rate", 0))

        if upper is None:
            return rate
        if funded <= float(upper):
            return rate

    return float(slabs[-1].get("annual_rate", 0)) if slabs else 0.0