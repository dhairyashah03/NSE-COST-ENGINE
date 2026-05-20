"""
Utility functions shared across the cost engine.

Key design choice: NSE rounds most charges to the nearest paisa (2 decimals).
We keep full precision during computation and only round at the final output
stage (CostBreakdown.as_dict). Internal functions return raw floats.
"""

from __future__ import annotations

from nse_cost_engine.models import Trade, Segment, TradeType, Side


def get_turnover_base(trade: Trade) -> float:
    """
    Determine the correct base amount for percentage‑based charges.

    - Equity / ETF / Futures: trade_value  (price × qty × lot_size)
    - Options: premium_value               (premium × qty × lot_size)

    This is the single most important helper — almost every charge module
    calls it. Getting this wrong means every downstream number is wrong.
    """
    if trade.segment == Segment.OPTIONS:
        return trade.premium_value
    return trade.trade_value


def is_delivery_sell(trade: Trade) -> bool:
    """Check if this trade triggers DP charges (delivery sell only)."""
    return (
        trade.side == Side.SELL
        and trade.trade_type in (TradeType.DELIVERY, TradeType.MTF)
        and trade.segment in (Segment.EQUITY, Segment.ETF)
    )


def is_delivery(trade: Trade) -> bool:
    """Check if this is a delivery‑type trade (includes MTF)."""
    return trade.trade_type in (TradeType.DELIVERY, TradeType.MTF)


def segment_key(trade: Trade) -> str:
    """
    Build the config lookup key for the trade's segment + trade_type.

    Examples:
        equity delivery  → 'equity_delivery'
        equity intraday  → 'equity_intraday'
        futures          → 'futures'
        options          → 'options'
        etf delivery     → 'etf_delivery'
        etf intraday     → 'etf_intraday'

    MTF uses the same rates as delivery (STT, stamp duty, exchange charges
    are identical — the only difference is MTF interest, handled separately).
    """
    seg = trade.segment.value  # 'equity', 'futures', 'options', 'etf'

    if seg in ("futures", "options"):
        return seg

    # equity / etf need trade_type qualifier
    tt = trade.trade_type
    if tt == TradeType.MTF:
        tt = TradeType.DELIVERY  # MTF uses delivery rates

    return f"{seg}_{tt.value}"