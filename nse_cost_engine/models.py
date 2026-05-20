"""
Data models for the NSE Transaction Cost Engine.

Defines the core data structures that flow through the entire system:
- Trade: input describing a single trade leg
- CostBreakdown: output with every cost component itemised
- RoundTripResult: buy + sell pair with net P&L after all costs

Design decision: we use dataclasses (not Pydantic) to keep dependencies
minimal and startup fast. Type hints + runtime checks in __post_init__
give us safety without the overhead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Segment(Enum):
    """Market segment — determines which STT / exchange‑charge schedule applies."""
    EQUITY = "equity"
    FUTURES = "futures"
    OPTIONS = "options"
    ETF = "etf"


class TradeType(Enum):
    """
    How the position is held.

    DELIVERY  – shares hit demat, held overnight+
    INTRADAY  – squared off same day
    MTF       – margin‑funded delivery (interest accrues)
    """
    DELIVERY = "delivery"
    INTRADAY = "intraday"
    MTF = "mtf"


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


class Exchange(Enum):
    NSE = "nse"
    BSE = "bse"


# ---------------------------------------------------------------------------
# Trade (input)
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    """
    Everything the cost engine needs to know about a single trade leg.

    For equity (delivery / intraday):
        price    = trade price per share
        quantity = number of shares
        lot_size = 1 (default)

    For futures:
        price    = futures price
        quantity = number of lots
        lot_size = contract lot size (e.g. 75 for Nifty)

    For options:
        price    = underlying price (informational)
        quantity = number of lots
        lot_size = contract lot size
        premium  = option premium per unit
    """

    symbol: str
    segment: Segment
    trade_type: TradeType
    side: Side
    exchange: Exchange
    price: float
    quantity: int
    lot_size: int = 1

    # --- Options‑specific ---------------------------------------------------
    premium: Optional[float] = None
    strike_price: Optional[float] = None
    settlement_price: Optional[float] = None
    is_exercise: bool = False

    # --- MTF‑specific -------------------------------------------------------
    mtf_leverage: Optional[float] = None      # e.g. 4.55 means 4.55× leverage
    mtf_holding_days: Optional[int] = None    # interest accrual days (caller computes)

    # --- Market impact (Phase 2) --------------------------------------------
    daily_volatility: Optional[float] = None
    avg_daily_volume: Optional[int] = None

    # -----------------------------------------------------------------------
    # Computed properties
    # -----------------------------------------------------------------------

    @property
    def trade_value(self) -> float:
        """
        Gross notional value of the trade.

        Equity : price × quantity
        Futures: price × quantity × lot_size
        Options: price × quantity × lot_size  (underlying notional, rarely used for costs)
        """
        return self.price * self.quantity * self.lot_size

    @property
    def premium_value(self) -> float:
        """
        For options: premium × quantity × lot_size.
        This is the base for STT, exchange charges, and stamp duty on options.
        Returns 0.0 for non‑option segments.
        """
        if self.segment == Segment.OPTIONS and self.premium is not None:
            return self.premium * self.quantity * self.lot_size
        return 0.0

    @property
    def intrinsic_value(self) -> float:
        """
        For exercised options: |settlement_price − strike_price| × quantity × lot_size.
        STT on exercise is levied on this, not on premium.
        """
        if (self.is_exercise
                and self.settlement_price is not None
                and self.strike_price is not None):
            return abs(self.settlement_price - self.strike_price) * self.quantity * self.lot_size
        return 0.0

    @property
    def mtf_funding_pct(self) -> float:
        """Derive funding % from leverage. 4× leverage = 75% funded, 4.55× = 78%."""
        if self.trade_type == TradeType.MTF and self.mtf_leverage is not None and self.mtf_leverage > 1:
            return 1 - (1 / self.mtf_leverage)
        return 0.0

    @property
    def funded_amount(self) -> float:
        """
        For MTF: the amount the broker funds.
        trade_value × (1 - 1/leverage)
        E.g. 4.55× leverage on ₹1,32,270 → funded = ₹1,03,199.67
        """
        if self.trade_type == TradeType.MTF and self.mtf_leverage is not None:
            return self.trade_value * self.mtf_funding_pct
        return 0.0

    @property
    def client_margin(self) -> float:
        """For MTF: the amount the client puts up. trade_value / leverage."""
        if self.trade_type == TradeType.MTF and self.mtf_leverage is not None and self.mtf_leverage > 0:
            return self.trade_value / self.mtf_leverage
        return 0.0

    def __post_init__(self) -> None:
        """Basic sanity checks — fail fast on bad inputs."""
        if self.price < 0:
            raise ValueError(f"price must be non‑negative, got {self.price}")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.lot_size <= 0:
            raise ValueError(f"lot_size must be positive, got {self.lot_size}")
        if self.segment == Segment.OPTIONS and self.premium is None and not self.is_exercise:
            raise ValueError("premium is required for options trades (unless is_exercise=True)")
        if self.trade_type == TradeType.MTF:
            if self.mtf_leverage is None:
                raise ValueError("mtf_leverage is required for MTF trades (e.g. 4.0 for 4× leverage)")
            if self.mtf_leverage < 1:
                raise ValueError(f"mtf_leverage must be >= 1, got {self.mtf_leverage}")


# ---------------------------------------------------------------------------
# CostBreakdown (output)
# ---------------------------------------------------------------------------

@dataclass
class CostBreakdown:
    """
    Itemised output of every cost component for a single trade leg.

    All amounts are in INR (₹), rounded to 2 decimal places in as_dict().
    The engine populates each field; consumers read total_cost or as_dict().
    """

    brokerage: float = 0.0
    stt: float = 0.0
    exchange_charges: float = 0.0
    sebi_fee: float = 0.0
    ipft: float = 0.0
    stamp_duty: float = 0.0
    gst: float = 0.0
    dp_charges: float = 0.0
    dp_charges_gst: float = 0.0
    mtf_interest: float = 0.0
    mtf_pledge_charges: float = 0.0
    mtf_pledge_gst: float = 0.0
    market_impact: float = 0.0

    # --- Aggregates --------------------------------------------------------

    @property
    def total_regulatory(self) -> float:
        """All government / exchange levies (excludes brokerage, impact, MTF)."""
        return (self.stt + self.exchange_charges + self.sebi_fee
                + self.ipft + self.stamp_duty + self.gst
                + self.dp_charges + self.dp_charges_gst)

    @property
    def total_cost(self) -> float:
        """Everything: brokerage + regulatory + DP + MTF + market impact."""
        return (self.brokerage + self.stt + self.exchange_charges
                + self.sebi_fee + self.ipft + self.stamp_duty
                + self.gst + self.dp_charges + self.dp_charges_gst
                + self.mtf_interest + self.mtf_pledge_charges
                + self.mtf_pledge_gst + self.market_impact)

    @property
    def total_cost_without_impact(self) -> float:
        """Total excluding market impact estimate."""
        return self.total_cost - self.market_impact

    @property
    def gst_total(self) -> float:
        """Combined GST: on (brokerage + exchange + SEBI + IPFT) and on DP charges."""
        return self.gst + self.dp_charges_gst

    # --- Serialisation -----------------------------------------------------

    def as_dict(self) -> Dict[str, float]:
        """
        Dictionary with every component rounded to 2 decimals.
        Useful for logging, Excel export, and JSON serialisation.
        """
        return {
            "brokerage": round(self.brokerage, 2),
            "stt": round(self.stt, 2),
            "exchange_charges": round(self.exchange_charges, 2),
            "sebi_fee": round(self.sebi_fee, 2),
            "ipft": round(self.ipft, 2),
            "stamp_duty": round(self.stamp_duty, 2),
            "gst": round(self.gst, 2),
            "dp_charges": round(self.dp_charges, 2),
            "dp_charges_gst": round(self.dp_charges_gst, 2),
            "mtf_interest": round(self.mtf_interest, 2),
            "mtf_pledge_charges": round(self.mtf_pledge_charges, 2),
            "mtf_pledge_gst": round(self.mtf_pledge_gst, 2),
            "market_impact": round(self.market_impact, 2),
            "total_regulatory": round(self.total_regulatory, 2),
            "total_cost": round(self.total_cost, 2),
        }

    def as_contract_note_dict(self) -> Dict[str, float]:
        """
        Dictionary with broker contract note rounding rules applied.

        Per Dhan (and most brokers):
        - STT and Stamp Duty are rounded to the nearest rupee
        - All other charges are rounded to the nearest 2 decimals
        """
        stt_rounded = round(self.stt)
        stamp_rounded = round(self.stamp_duty)

        return {
            "brokerage": round(self.brokerage, 2),
            "stt": float(stt_rounded),
            "exchange_charges": round(self.exchange_charges, 2),
            "sebi_fee": round(self.sebi_fee, 2),
            "ipft": round(self.ipft, 2),
            "stamp_duty": float(stamp_rounded),
            "gst": round(self.gst, 2),
            "dp_charges": round(self.dp_charges, 2),
            "dp_charges_gst": round(self.dp_charges_gst, 2),
            "mtf_interest": round(self.mtf_interest, 2),
            "mtf_pledge_charges": round(self.mtf_pledge_charges, 2),
            "mtf_pledge_gst": round(self.mtf_pledge_gst, 2),
            "market_impact": round(self.market_impact, 2),
            "total_cost": round(
                self.brokerage + stt_rounded + self.exchange_charges
                + self.sebi_fee + self.ipft + stamp_rounded
                + self.gst + self.dp_charges + self.dp_charges_gst
                + self.mtf_interest + self.mtf_pledge_charges
                + self.mtf_pledge_gst + self.market_impact, 2
            ),
        }


# ---------------------------------------------------------------------------
# RoundTripResult (buy + sell aggregate)
# ---------------------------------------------------------------------------

@dataclass
class RoundTripResult:
    """
    Wraps a complete buy→sell cycle with net P&L after all costs.

    This is what strategy backtests consume: 'I bought at X, sold at Y,
    what's my real P&L after every cost is deducted?'
    """

    buy_costs: CostBreakdown
    sell_costs: CostBreakdown
    buy_value: float       # price × qty × lot_size on entry
    sell_value: float      # price × qty × lot_size on exit
    quantity: int
    lot_size: int = 1

    @property
    def total_costs(self) -> float:
        return self.buy_costs.total_cost + self.sell_costs.total_cost

    @property
    def gross_pnl(self) -> float:
        """Profit before any costs."""
        return self.sell_value - self.buy_value

    @property
    def net_pnl(self) -> float:
        """Profit after all costs."""
        return self.gross_pnl - self.total_costs

    @property
    def cost_as_pct_of_turnover(self) -> float:
        """Total costs as % of one‑side turnover (buy value)."""
        if self.buy_value == 0:
            return 0.0
        return (self.total_costs / self.buy_value) * 100

    @property
    def breakeven_move_pct(self) -> float:
        """
        Minimum price movement (%) needed to cover round‑trip costs.
        This is what a trader looks at before deciding 'is this signal
        worth executing?'
        """
        if self.buy_value == 0:
            return 0.0
        return (self.total_costs / self.buy_value) * 100

    def as_dict(self) -> Dict[str, Any]:
        return {
            "buy_costs": self.buy_costs.as_dict(),
            "sell_costs": self.sell_costs.as_dict(),
            "buy_value": round(self.buy_value, 2),
            "sell_value": round(self.sell_value, 2),
            "gross_pnl": round(self.gross_pnl, 2),
            "net_pnl": round(self.net_pnl, 2),
            "total_costs": round(self.total_costs, 2),
            "breakeven_move_pct": round(self.breakeven_move_pct, 4),
        }