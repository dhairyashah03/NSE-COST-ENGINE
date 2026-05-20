"""
CostEngine — the main entry point for the NSE Transaction Cost Engine.

This class orchestrates all calculator modules into a single, clean API.
Every other project imports this.

Usage:
    from nse_cost_engine import CostEngine, Trade, Segment, TradeType, Side, Exchange

    engine = CostEngine(broker="dhan")
    result = engine.calculate(trade)
    print(result.total_cost)
    print(result.as_dict())

Design decisions:
- CostEngine is stateful (holds config) but immutable after __init__.
- calculate() is a pure function of (trade, config) — no side effects.
- what_if() creates a temporary config overlay without mutating state.
- Logging is built in from day one — every calculation is traceable.
"""

from __future__ import annotations

import copy
import logging
from typing import Dict, Any, Optional

from nse_cost_engine.models import (
    Trade, CostBreakdown, RoundTripResult,
    Segment, TradeType, Side, Exchange,
)
from nse_cost_engine.config_loader import load_config, get_rate, _deep_merge
from nse_cost_engine.brokerage import calculate_brokerage
from nse_cost_engine.regulatory import (
    calculate_stt, calculate_sebi_fee,
    calculate_ipft, calculate_stamp_duty,
)
from nse_cost_engine.exchange import calculate_exchange_charges
from nse_cost_engine.tax import calculate_gst
from nse_cost_engine.dp_charges import calculate_dp_charges
from nse_cost_engine.mtf import calculate_mtf_interest, calculate_mtf_pledge_charges
from nse_cost_engine.market_impact import calculate_market_impact


logger = logging.getLogger("nse_cost_engine")


class CostEngine:
    """
    NSE Transaction Cost Engine.

    Loads a rate configuration (default + broker profile) once at init,
    then computes costs for any number of trades against that config.

    Parameters
    ----------
    broker : str
        Name of broker profile (must match a YAML in config/broker_profiles/).
    config_path : str, optional
        Override path to default_rates.yaml.
    broker_path : str, optional
        Override path to broker profile YAML.
    impact_model : str
        Market impact model: 'sqrt' or 'almgren_chriss'. Default 'sqrt'.
    """

    def __init__(
        self,
        broker: str = "dhan",
        config_path: Optional[str] = None,
        broker_path: Optional[str] = None,
        impact_model: str = "sqrt",
    ):
        self._config = load_config(
            broker=broker,
            config_path=config_path,
            broker_path=broker_path,
        )
        self._broker = self._config.get("_broker_name", broker)
        self._impact_model = impact_model

        logger.info(
            "CostEngine initialised | broker=%s | config_version=%s | effective=%s",
            self._broker,
            self._config.get("version", "?"),
            self._config.get("effective_date", "?"),
        )

    @property
    def broker_name(self) -> str:
        return self._broker

    @property
    def config(self) -> Dict[str, Any]:
        """Read‑only access to the merged config (for inspection / debugging)."""
        return copy.deepcopy(self._config)

    # -----------------------------------------------------------------------
    # Core API
    # -----------------------------------------------------------------------

    def calculate(self, trade: Trade) -> CostBreakdown:
        """
        Compute the full cost breakdown for a single trade leg.

        This is the workhorse method. It calls each calculator module in
        the correct order (some modules depend on outputs of earlier ones).

        Parameters
        ----------
        trade : Trade

        Returns
        -------
        CostBreakdown
        """
        cfg = self._config
        breakdown = CostBreakdown()

        # 1. Brokerage (independent)
        breakdown.brokerage = calculate_brokerage(trade, cfg)

        # 2. STT (independent)
        breakdown.stt = calculate_stt(trade, cfg)

        # 3. Exchange transaction charges (independent)
        breakdown.exchange_charges = calculate_exchange_charges(trade, cfg)

        # 4. SEBI turnover fee (independent)
        breakdown.sebi_fee = calculate_sebi_fee(trade, cfg)

        # 5. IPFT (independent)
        breakdown.ipft = calculate_ipft(trade, cfg)

        # 6. Stamp duty (independent)
        breakdown.stamp_duty = calculate_stamp_duty(trade, cfg)

        # 7. GST — depends on brokerage, exchange, sebi, ipft
        breakdown.gst = calculate_gst(
            brokerage=breakdown.brokerage,
            exchange_charges=breakdown.exchange_charges,
            sebi_fee=breakdown.sebi_fee,
            ipft=breakdown.ipft,
            config=cfg,
        )

        # 8. DP charges — delivery sell only, with its own GST
        breakdown.dp_charges, breakdown.dp_charges_gst = calculate_dp_charges(trade, cfg)

        # 9. MTF interest — MTF buy side only
        breakdown.mtf_interest = calculate_mtf_interest(trade, cfg)

        # 10. MTF pledge/unpledge charges — both buy and sell legs
        breakdown.mtf_pledge_charges, breakdown.mtf_pledge_gst = calculate_mtf_pledge_charges(trade, cfg)

        # 11. Market impact (optional — only if vol + volume data provided)
        breakdown.market_impact = calculate_market_impact(
            trade, cfg, model=self._impact_model,
        )

        logger.debug(
            "calculate | symbol=%s | segment=%s | side=%s | value=%.2f | total_cost=%.2f",
            trade.symbol, trade.segment.value, trade.side.value,
            trade.trade_value, breakdown.total_cost,
        )

        return breakdown

    def round_trip(
        self,
        buy_trade: Trade,
        sell_trade: Trade,
    ) -> RoundTripResult:
        """
        Compute costs for a complete buy → sell cycle.

        Returns a RoundTripResult with both legs' costs and net P&L.
        """
        buy_costs = self.calculate(buy_trade)
        sell_costs = self.calculate(sell_trade)

        result = RoundTripResult(
            buy_costs=buy_costs,
            sell_costs=sell_costs,
            buy_value=buy_trade.trade_value,
            sell_value=sell_trade.trade_value,
            quantity=buy_trade.quantity,
            lot_size=buy_trade.lot_size,
        )

        logger.info(
            "round_trip | symbol=%s | gross_pnl=%.2f | total_costs=%.2f | "
            "net_pnl=%.2f | breakeven=%.4f%%",
            buy_trade.symbol, result.gross_pnl, result.total_costs,
            result.net_pnl, result.breakeven_move_pct,
        )

        return result

    def breakeven(self, trade: Trade) -> float:
        """
        Calculate the breakeven price move (%) for a round trip.

        Uses iterative solving: sell-side costs depend on the sell price,
        which depends on the breakeven. Converges in 3-5 iterations.

        The approach: start with a rough sell price estimate (e.g. 5% above buy),
        compute total costs, derive breakeven, update sell price, repeat.
        """
        buy_trade = trade
        buy_costs = self.calculate(buy_trade)
        units = trade.quantity * trade.lot_size

        if units == 0 or trade.price == 0:
            return 0.0

        # Start with a sell price estimate ~5% above buy
        # This ensures sell-side costs are computed at a realistic price
        sell_price = trade.price * 1.05

        for _ in range(20):
            sell_trade = Trade(
                symbol=trade.symbol,
                segment=trade.segment,
                trade_type=trade.trade_type,
                side=Side.SELL,
                exchange=trade.exchange,
                price=sell_price,
                quantity=trade.quantity,
                lot_size=trade.lot_size,
                premium=trade.premium,
                strike_price=trade.strike_price,
                daily_volatility=trade.daily_volatility,
                avg_daily_volume=trade.avg_daily_volume,
                mtf_leverage=trade.mtf_leverage,
                mtf_holding_days=trade.mtf_holding_days,
            )
            sell_costs = self.calculate(sell_trade)
            total_costs = buy_costs.total_cost + sell_costs.total_cost

            # New sell price = buy price + total costs per unit
            new_sell_price = trade.price + (total_costs / units)

            if abs(new_sell_price - sell_price) < 0.005:
                sell_price = new_sell_price
                break
            sell_price = new_sell_price

        return ((sell_price - trade.price) / trade.price) * 100

    def what_if(self, trade: Trade, **overrides: Any) -> CostBreakdown:
        """
        Recalculate with temporary config overrides.

        Useful for sensitivity analysis:
            engine.what_if(trade, broker='zerodha')
            engine.what_if(trade, stt={'futures': {'rate': 0.0002}})

        The engine's internal config is NOT mutated.
        """
        temp_config = _deep_merge(self._config, overrides)

        # Create a temporary engine-like context
        original = self._config
        try:
            self._config = temp_config
            result = self.calculate(trade)
        finally:
            self._config = original

        return result