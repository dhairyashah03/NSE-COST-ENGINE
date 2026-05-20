"""
NSE Transaction Cost Engine
===========================

Production‑grade cost modelling for NSE trades across all segments:
equity (delivery & intraday), F&O (futures & options), ETFs, and MTF.

Quick start:
    >>> from nse_cost_engine import CostEngine, Trade, Segment, TradeType, Side, Exchange
    >>> engine = CostEngine(broker="dhan")
    >>> trade = Trade(
    ...     symbol="RELIANCE",
    ...     segment=Segment.EQUITY,
    ...     trade_type=TradeType.INTRADAY,
    ...     side=Side.SELL,
    ...     exchange=Exchange.NSE,
    ...     price=2450.0,
    ...     quantity=100,
    ... )
    >>> result = engine.calculate(trade)
    >>> print(result.total_cost)
"""

from nse_cost_engine.models import (
    Trade,
    CostBreakdown,
    RoundTripResult,
    Segment,
    TradeType,
    Side,
    Exchange,
)
from nse_cost_engine.engine import CostEngine

__version__ = "0.1.0"
__all__ = [
    "CostEngine",
    "Trade",
    "CostBreakdown",
    "RoundTripResult",
    "Segment",
    "TradeType",
    "Side",
    "Exchange",
]