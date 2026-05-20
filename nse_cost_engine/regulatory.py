"""
Regulatory charges: STT, SEBI turnover fee, stamp duty, IPFT.

These are all government / regulator‑mandated levies. They share the same
pattern: rate × base_amount × side_applicability, which is why they live
in one module rather than four separate files.

Each function is independently callable and testable.
"""

from __future__ import annotations

from typing import Dict, Any

from nse_cost_engine.models import Trade, Segment, TradeType, Side
from nse_cost_engine.utils import segment_key, get_turnover_base
from nse_cost_engine.config_loader import get_rate


# ============================================================================
# STT — Securities Transaction Tax
# ============================================================================

def calculate_stt(trade: Trade, config: Dict[str, Any]) -> float:
    """
    Calculate Securities Transaction Tax.

    STT rules are segment‑ and side‑specific:
    - Equity delivery: 0.1% on both buy AND sell
    - Equity intraday: 0.025% on sell only
    - Futures: 0.05% on sell only (on notional)
    - Options: 0.15% on sell only (on premium)
    - Exercised options: 0.15% on intrinsic value
    - ETF delivery: 0.001% on sell only
    - ETF intraday: 0.025% on sell only
    """
    stt_config = config.get("stt", {})

    # --- Handle exercised options separately --------------------------------
    if trade.is_exercise and trade.segment == Segment.OPTIONS:
        ex_config = stt_config.get("options_exercise", {})
        rate = float(ex_config.get("rate", 0))
        return trade.intrinsic_value * rate

    # --- Standard STT -------------------------------------------------------
    key = segment_key(trade)
    entry = stt_config.get(key, {})
    rate = float(entry.get("rate", 0))
    side_rule = entry.get("side", "sell")

    # Determine if this trade side is subject to STT
    if side_rule == "both":
        # Charged on both buy and sell (equity delivery)
        pass
    elif side_rule == "sell" and trade.side != Side.SELL:
        return 0.0
    elif side_rule == "buy" and trade.side != Side.BUY:
        return 0.0

    # Determine the base amount
    base_on = entry.get("base_on", "trade_value")
    if base_on == "premium_value":
        base = trade.premium_value
    elif base_on == "intrinsic_value":
        base = trade.intrinsic_value
    else:
        base = trade.trade_value

    return base * rate


# ============================================================================
# SEBI Turnover Fee
# ============================================================================

def calculate_sebi_fee(trade: Trade, config: Dict[str, Any]) -> float:
    """
    SEBI turnover fee: uniform 0.0001% (₹10 per crore) on all segments.
    Charged on both sides, on turnover base (trade_value or premium_value).
    """
    rate = get_rate(config, "sebi_turnover_fee", "rate")
    base = get_turnover_base(trade)
    return base * rate


# ============================================================================
# IPFT — Investor Protection Fund Trust
# ============================================================================

def calculate_ipft(trade: Trade, config: Dict[str, Any]) -> float:
    """
    IPFT contribution: 0.0000001% of turnover.
    Negligible individually, but part of the GST base.
    """
    rate = get_rate(config, "ipft", "rate")
    base = get_turnover_base(trade)
    return base * rate


# ============================================================================
# Stamp Duty
# ============================================================================

def calculate_stamp_duty(trade: Trade, config: Dict[str, Any]) -> float:
    """
    Stamp duty — charged on BUY side only (post‑2020 reform).

    Rates differ by segment:
    - Equity delivery: 0.015%
    - Equity intraday: 0.003%
    - Futures: 0.002%
    - Options: 0.003% (on premium)
    - ETF: same as equity

    For options, stamp duty is on premium_value (not on notional).
    """
    # Stamp duty is buy-side only
    if trade.side != Side.BUY:
        return 0.0

    stamp_config = config.get("stamp_duty", {})
    key = segment_key(trade)
    rate = float(stamp_config.get(key, 0))
    base = get_turnover_base(trade)

    return base * rate