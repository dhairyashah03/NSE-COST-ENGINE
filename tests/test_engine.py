"""
Test suite for the NSE Transaction Cost Engine.

Tests are organised by module, with an integration section at the end
that validates full end‑to‑end calculations against hand‑computed values.

Every test uses Dhan's real rates so outputs can be cross‑checked against
Dhan's brokerage calculator or actual contract notes.
"""

import pytest
import math
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nse_cost_engine import (
    CostEngine, Trade, CostBreakdown, RoundTripResult,
    Segment, TradeType, Side, Exchange,
)
from nse_cost_engine.brokerage import calculate_brokerage
from nse_cost_engine.regulatory import (
    calculate_stt, calculate_sebi_fee,
    calculate_ipft, calculate_stamp_duty,
)
from nse_cost_engine.exchange import calculate_exchange_charges
from nse_cost_engine.tax import calculate_gst
from nse_cost_engine.dp_charges import calculate_dp_charges
from nse_cost_engine.mtf import calculate_mtf_interest
from nse_cost_engine.market_impact import calculate_market_impact
from nse_cost_engine.config_loader import load_config


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def dhan_config():
    return load_config(broker="dhan")

@pytest.fixture
def engine():
    return CostEngine(broker="dhan")

# --- Sample trades ----------------------------------------------------------

@pytest.fixture
def equity_delivery_buy():
    """Buy 100 shares of RELIANCE at ₹2,450 delivery on NSE."""
    return Trade(
        symbol="RELIANCE",
        segment=Segment.EQUITY,
        trade_type=TradeType.DELIVERY,
        side=Side.BUY,
        exchange=Exchange.NSE,
        price=2450.0,
        quantity=100,
    )

@pytest.fixture
def equity_delivery_sell():
    return Trade(
        symbol="RELIANCE",
        segment=Segment.EQUITY,
        trade_type=TradeType.DELIVERY,
        side=Side.SELL,
        exchange=Exchange.NSE,
        price=2500.0,
        quantity=100,
    )

@pytest.fixture
def equity_intraday_sell():
    """Sell 200 shares of TCS at ₹3,800 intraday on NSE."""
    return Trade(
        symbol="TCS",
        segment=Segment.EQUITY,
        trade_type=TradeType.INTRADAY,
        side=Side.SELL,
        exchange=Exchange.NSE,
        price=3800.0,
        quantity=200,
    )

@pytest.fixture
def nifty_futures_sell():
    """Sell 1 lot of Nifty futures at ₹24,500 on NSE."""
    return Trade(
        symbol="NIFTY",
        segment=Segment.FUTURES,
        trade_type=TradeType.INTRADAY,
        side=Side.SELL,
        exchange=Exchange.NSE,
        price=24500.0,
        quantity=1,
        lot_size=75,
    )

@pytest.fixture
def nifty_options_sell():
    """Sell 1 lot of Nifty 24400 CE at premium ₹150 on NSE."""
    return Trade(
        symbol="NIFTY",
        segment=Segment.OPTIONS,
        trade_type=TradeType.INTRADAY,
        side=Side.SELL,
        exchange=Exchange.NSE,
        price=24500.0,
        quantity=1,
        lot_size=75,
        premium=150.0,
        strike_price=24400.0,
    )

@pytest.fixture
def nifty_options_exercise():
    """Exercised Nifty 24000 CE, settlement at 24500."""
    return Trade(
        symbol="NIFTY",
        segment=Segment.OPTIONS,
        trade_type=TradeType.INTRADAY,
        side=Side.SELL,
        exchange=Exchange.NSE,
        price=24500.0,
        quantity=1,
        lot_size=75,
        premium=150.0,
        strike_price=24000.0,
        settlement_price=24500.0,
        is_exercise=True,
    )

@pytest.fixture
def mtf_buy():
    """Buy ₹10L of HDFC Bank via MTF, held for 7 days."""
    return Trade(
        symbol="HDFCBANK",
        segment=Segment.EQUITY,
        trade_type=TradeType.MTF,
        side=Side.BUY,
        exchange=Exchange.NSE,
        price=1600.0,
        quantity=625,  # 625 × 1600 = ₹10,00,000
        mtf_funding_pct=0.75,
        mtf_holding_days=7,
    )


# ============================================================================
# Brokerage Tests
# ============================================================================

class TestBrokerage:
    def test_zero_brokerage_delivery(self, equity_delivery_buy, dhan_config):
        """Dhan charges zero brokerage on equity delivery."""
        result = calculate_brokerage(equity_delivery_buy, dhan_config)
        assert result == 0.0

    def test_flat_brokerage_futures(self, nifty_futures_sell, dhan_config):
        """Dhan charges flat ₹20 on futures."""
        result = calculate_brokerage(nifty_futures_sell, dhan_config)
        assert result == 20.0

    def test_flat_brokerage_options(self, nifty_options_sell, dhan_config):
        """Dhan charges flat ₹20 on options."""
        result = calculate_brokerage(nifty_options_sell, dhan_config)
        assert result == 20.0

    def test_min_of_brokerage_intraday_small(self, dhan_config):
        """For small trades, percentage < ₹20, so percentage wins."""
        small_trade = Trade(
            symbol="IDEA", segment=Segment.EQUITY,
            trade_type=TradeType.INTRADAY, side=Side.BUY,
            exchange=Exchange.NSE, price=10.0, quantity=100,
        )
        # trade_value = 1000, 0.03% = ₹0.30, min(20, 0.30) = 0.30
        result = calculate_brokerage(small_trade, dhan_config)
        assert abs(result - 0.30) < 0.01

    def test_min_of_brokerage_intraday_large(self, dhan_config):
        """For large trades, ₹20 < percentage, so ₹20 wins."""
        large_trade = Trade(
            symbol="RELIANCE", segment=Segment.EQUITY,
            trade_type=TradeType.INTRADAY, side=Side.BUY,
            exchange=Exchange.NSE, price=2450.0, quantity=500,
        )
        # trade_value = 12,25,000, 0.03% = ₹367.50, min(20, 367.50) = 20
        result = calculate_brokerage(large_trade, dhan_config)
        assert result == 20.0


# ============================================================================
# STT Tests
# ============================================================================

class TestSTT:
    def test_equity_delivery_buy_stt(self, equity_delivery_buy, dhan_config):
        """Equity delivery: 0.1% on buy side."""
        result = calculate_stt(equity_delivery_buy, dhan_config)
        expected = 2450.0 * 100 * 0.001  # ₹245.00
        assert abs(result - expected) < 0.01

    def test_equity_delivery_sell_stt(self, equity_delivery_sell, dhan_config):
        """Equity delivery: 0.1% on sell side too."""
        result = calculate_stt(equity_delivery_sell, dhan_config)
        expected = 2500.0 * 100 * 0.001  # ₹250.00
        assert abs(result - expected) < 0.01

    def test_equity_intraday_buy_no_stt(self, dhan_config):
        """Equity intraday: zero STT on buy side."""
        buy = Trade(
            symbol="TCS", segment=Segment.EQUITY,
            trade_type=TradeType.INTRADAY, side=Side.BUY,
            exchange=Exchange.NSE, price=3800.0, quantity=200,
        )
        result = calculate_stt(buy, dhan_config)
        assert result == 0.0

    def test_equity_intraday_sell_stt(self, equity_intraday_sell, dhan_config):
        """Equity intraday: 0.025% on sell side."""
        result = calculate_stt(equity_intraday_sell, dhan_config)
        expected = 3800.0 * 200 * 0.00025  # ₹190.00
        assert abs(result - expected) < 0.01

    def test_futures_sell_stt(self, nifty_futures_sell, dhan_config):
        """Futures: 0.05% on sell side (notional)."""
        result = calculate_stt(nifty_futures_sell, dhan_config)
        expected = 24500.0 * 75 * 0.0005  # ₹918.75
        assert abs(result - expected) < 0.01

    def test_options_sell_stt_on_premium(self, nifty_options_sell, dhan_config):
        """Options: 0.15% on sell side, on premium value."""
        result = calculate_stt(nifty_options_sell, dhan_config)
        expected = 150.0 * 75 * 0.0015  # ₹16.875
        assert abs(result - expected) < 0.01

    def test_options_exercise_stt_on_intrinsic(self, nifty_options_exercise, dhan_config):
        """Exercised options: 0.15% on intrinsic value."""
        result = calculate_stt(nifty_options_exercise, dhan_config)
        # intrinsic = |24500 - 24000| × 75 = 37,500
        expected = 37500.0 * 0.0015  # ₹56.25
        assert abs(result - expected) < 0.01


# ============================================================================
# Exchange Charges Tests
# ============================================================================

class TestExchangeCharges:
    def test_nse_equity(self, equity_delivery_buy, dhan_config):
        """NSE equity: 0.0030699% of trade value."""
        result = calculate_exchange_charges(equity_delivery_buy, dhan_config)
        expected = 2450.0 * 100 * 0.000030699  # ₹7.52
        assert abs(result - expected) < 0.01

    def test_nse_futures(self, nifty_futures_sell, dhan_config):
        """NSE futures: 0.0018299% of notional."""
        result = calculate_exchange_charges(nifty_futures_sell, dhan_config)
        expected = 24500.0 * 75 * 0.000018299  # ₹33.62
        assert abs(result - expected) < 0.1

    def test_nse_options_on_premium(self, nifty_options_sell, dhan_config):
        """NSE options: 0.0355299% on premium value."""
        result = calculate_exchange_charges(nifty_options_sell, dhan_config)
        expected = 150.0 * 75 * 0.000355299  # ₹3.997
        assert abs(result - expected) < 0.01


# ============================================================================
# SEBI Fee & IPFT Tests
# ============================================================================

class TestSEBIandIPFT:
    def test_sebi_fee(self, equity_delivery_buy, dhan_config):
        """SEBI fee: 0.0001% of turnover."""
        result = calculate_sebi_fee(equity_delivery_buy, dhan_config)
        expected = 245000.0 * 0.000001  # ₹0.245
        assert abs(result - expected) < 0.001

    def test_ipft(self, equity_delivery_buy, dhan_config):
        """IPFT: 0.0000001% of turnover — negligible but correct."""
        result = calculate_ipft(equity_delivery_buy, dhan_config)
        expected = 245000.0 * 0.000000001  # ₹0.000245
        assert abs(result - expected) < 0.0001


# ============================================================================
# Stamp Duty Tests
# ============================================================================

class TestStampDuty:
    def test_stamp_buy_only(self, equity_delivery_sell, dhan_config):
        """Stamp duty is buy-side only — sell should be zero."""
        result = calculate_stamp_duty(equity_delivery_sell, dhan_config)
        assert result == 0.0

    def test_delivery_stamp(self, equity_delivery_buy, dhan_config):
        """Equity delivery: 0.015% on buy turnover."""
        result = calculate_stamp_duty(equity_delivery_buy, dhan_config)
        expected = 245000.0 * 0.00015  # ₹36.75
        assert abs(result - expected) < 0.01

    def test_futures_stamp(self, dhan_config):
        """Futures: 0.002% on buy side."""
        buy = Trade(
            symbol="NIFTY", segment=Segment.FUTURES,
            trade_type=TradeType.INTRADAY, side=Side.BUY,
            exchange=Exchange.NSE, price=24500.0, quantity=1, lot_size=75,
        )
        result = calculate_stamp_duty(buy, dhan_config)
        expected = 24500.0 * 75 * 0.00002  # ₹36.75
        assert abs(result - expected) < 0.01

    def test_options_stamp_on_premium(self, dhan_config):
        """Options stamp duty: 0.003% on premium, buy side."""
        buy = Trade(
            symbol="NIFTY", segment=Segment.OPTIONS,
            trade_type=TradeType.INTRADAY, side=Side.BUY,
            exchange=Exchange.NSE, price=24500.0, quantity=1,
            lot_size=75, premium=150.0, strike_price=24400.0,
        )
        result = calculate_stamp_duty(buy, dhan_config)
        expected = 150.0 * 75 * 0.00003  # ₹0.3375
        assert abs(result - expected) < 0.001


# ============================================================================
# GST Tests
# ============================================================================

class TestGST:
    def test_gst_calculation(self, dhan_config):
        """GST = 18% × (brokerage + exchange + SEBI + IPFT)."""
        result = calculate_gst(
            brokerage=20.0,
            exchange_charges=5.0,
            sebi_fee=0.5,
            ipft=0.001,
            config=dhan_config,
        )
        expected = 0.18 * (20.0 + 5.0 + 0.5 + 0.001)  # ₹4.5902
        assert abs(result - expected) < 0.001

    def test_gst_zero_brokerage(self, dhan_config):
        """With zero brokerage, GST only on exchange + SEBI + IPFT."""
        result = calculate_gst(
            brokerage=0.0,
            exchange_charges=7.5,
            sebi_fee=0.25,
            ipft=0.0002,
            config=dhan_config,
        )
        expected = 0.18 * (7.5 + 0.25 + 0.0002)
        assert abs(result - expected) < 0.001


# ============================================================================
# DP Charges Tests
# ============================================================================

class TestDPCharges:
    def test_dp_on_delivery_sell(self, equity_delivery_sell, dhan_config):
        """DP charges apply on delivery sell: ₹12.50 + GST."""
        base, gst = calculate_dp_charges(equity_delivery_sell, dhan_config)
        assert abs(base - 12.50) < 0.01
        assert abs(gst - 12.50 * 0.18) < 0.01  # ₹2.25

    def test_no_dp_on_buy(self, equity_delivery_buy, dhan_config):
        """No DP charges on buy side."""
        base, gst = calculate_dp_charges(equity_delivery_buy, dhan_config)
        assert base == 0.0
        assert gst == 0.0

    def test_no_dp_on_intraday(self, equity_intraday_sell, dhan_config):
        """No DP charges on intraday."""
        base, gst = calculate_dp_charges(equity_intraday_sell, dhan_config)
        assert base == 0.0

    def test_no_dp_on_fno(self, nifty_futures_sell, dhan_config):
        """No DP charges on F&O (cash settled)."""
        base, gst = calculate_dp_charges(nifty_futures_sell, dhan_config)
        assert base == 0.0


# ============================================================================
# MTF Interest Tests
# ============================================================================

class TestMTFInterest:
    def test_mtf_interest_basic(self, mtf_buy, dhan_config):
        """
        MTF: ₹10L trade, 75% funded = ₹7.5L funded, 7 days.
        ₹7.5L is in slab 2 (₹5L–₹10L) → 13.49% p.a.
        Daily interest = 750000 × 0.1349 / 365 = ₹277.25
        7-day interest = ₹277.25 × 7 = ₹1940.75
        """
        result = calculate_mtf_interest(mtf_buy, dhan_config)
        expected_daily = 750000 * 0.1349 / 365
        expected = expected_daily * 7
        assert abs(result - expected) < 0.1

    def test_mtf_zero_days(self, dhan_config):
        """Zero holding days → zero interest."""
        trade = Trade(
            symbol="HDFCBANK", segment=Segment.EQUITY,
            trade_type=TradeType.MTF, side=Side.BUY,
            exchange=Exchange.NSE, price=1600.0, quantity=625,
            mtf_funding_pct=0.75, mtf_holding_days=0,
        )
        result = calculate_mtf_interest(trade, dhan_config)
        assert result == 0.0

    def test_mtf_not_applicable(self, equity_delivery_buy, dhan_config):
        """Non-MTF trade → zero interest."""
        result = calculate_mtf_interest(equity_delivery_buy, dhan_config)
        assert result == 0.0

    def test_mtf_slab_boundary(self, dhan_config):
        """₹5L funded → slab 1 (12.49%), ₹5,00,001 → slab 2 (13.49%)."""
        # Exactly at boundary
        t1 = Trade(
            symbol="X", segment=Segment.EQUITY,
            trade_type=TradeType.MTF, side=Side.BUY,
            exchange=Exchange.NSE, price=100.0, quantity=6667,
            mtf_funding_pct=0.75, mtf_holding_days=1,
        )
        # funded = 6667 * 100 * 0.75 = 500,025 → slab 2 (13.49%)
        result = calculate_mtf_interest(t1, dhan_config)
        expected = 500025 * 0.1349 / 365
        assert abs(result - expected) < 0.1

    def test_mtf_highest_slab(self, dhan_config):
        """₹60L funded → slab 5 (16.49%)."""
        trade = Trade(
            symbol="X", segment=Segment.EQUITY,
            trade_type=TradeType.MTF, side=Side.BUY,
            exchange=Exchange.NSE, price=1000.0, quantity=8000,
            mtf_funding_pct=0.75, mtf_holding_days=1,
        )
        # funded = 8000 * 1000 * 0.75 = 60,00,000 → slab 5
        result = calculate_mtf_interest(trade, dhan_config)
        expected = 6000000 * 0.1649 / 365
        assert abs(result - expected) < 0.1


# ============================================================================
# Market Impact Tests
# ============================================================================

class TestMarketImpact:
    def test_sqrt_impact(self, dhan_config):
        """Square-root model with known inputs."""
        trade = Trade(
            symbol="RELIANCE", segment=Segment.EQUITY,
            trade_type=TradeType.INTRADAY, side=Side.BUY,
            exchange=Exchange.NSE, price=2450.0, quantity=10000,
            daily_volatility=0.02,
            avg_daily_volume=5000000,
        )
        result = calculate_market_impact(trade, dhan_config, model="sqrt")
        # impact = 0.02 × √(10000/5000000) × 0.3 × 2450 × 10000
        participation = 10000 / 5000000
        expected = 0.02 * math.sqrt(participation) * 0.3 * 2450 * 10000
        assert abs(result - expected) < 0.01

    def test_no_impact_without_data(self, equity_delivery_buy, dhan_config):
        """No vol/volume data → zero impact."""
        result = calculate_market_impact(equity_delivery_buy, dhan_config)
        assert result == 0.0


# ============================================================================
# Integration Tests — Full Engine
# ============================================================================

class TestEngineIntegration:
    def test_equity_delivery_buy_full(self, engine, equity_delivery_buy):
        """
        Full cost breakdown for RELIANCE delivery buy, 100 shares @ ₹2,450.
        Trade value = ₹2,45,000

        Expected (hand-computed with Dhan rates):
            Brokerage:       ₹0.00 (zero for delivery)
            STT:             ₹245.00 (0.1% both sides)
            Exchange:        ₹7.52 (0.0030699%)
            SEBI:            ₹0.245
            IPFT:            ₹0.000245
            Stamp Duty:      ₹36.75 (0.015% buy side)
            GST:             18% × (0 + 7.52 + 0.245 + 0.000245) = ₹1.40
            DP:              ₹0.00 (buy side)
            MTF Interest:    ₹0.00
            Market Impact:   ₹0.00
        """
        result = engine.calculate(equity_delivery_buy)

        assert abs(result.brokerage - 0.0) < 0.01
        assert abs(result.stt - 245.0) < 0.01
        assert abs(result.exchange_charges - 7.52) < 0.1
        assert abs(result.stamp_duty - 36.75) < 0.01
        assert result.dp_charges == 0.0
        assert result.mtf_interest == 0.0
        assert result.total_cost > 289  # sanity: at least STT + stamp

    def test_equity_delivery_sell_full(self, engine, equity_delivery_sell):
        """
        RELIANCE delivery sell, 100 shares @ ₹2,500.
        Should include DP charges.
        """
        result = engine.calculate(equity_delivery_sell)

        assert abs(result.stt - 250.0) < 0.01
        assert abs(result.dp_charges - 12.50) < 0.01
        assert abs(result.dp_charges_gst - 2.25) < 0.01
        assert result.stamp_duty == 0.0  # sell side, no stamp

    def test_options_sell_full(self, engine, nifty_options_sell):
        """
        Nifty options sell, 1 lot, premium ₹150.
        Premium value = 150 × 75 = ₹11,250
        """
        result = engine.calculate(nifty_options_sell)

        assert abs(result.brokerage - 20.0) < 0.01
        assert abs(result.stt - 16.875) < 0.01
        assert result.stamp_duty == 0.0  # sell side
        assert result.dp_charges == 0.0  # F&O, no DP

    def test_round_trip(self, engine):
        """Full round trip: buy and sell RELIANCE delivery."""
        buy = Trade(
            symbol="RELIANCE", segment=Segment.EQUITY,
            trade_type=TradeType.DELIVERY, side=Side.BUY,
            exchange=Exchange.NSE, price=2450.0, quantity=100,
        )
        sell = Trade(
            symbol="RELIANCE", segment=Segment.EQUITY,
            trade_type=TradeType.DELIVERY, side=Side.SELL,
            exchange=Exchange.NSE, price=2500.0, quantity=100,
        )
        rt = engine.round_trip(buy, sell)

        assert abs(rt.gross_pnl - 5000.0) < 0.01  # (2500-2450) × 100
        assert rt.total_costs > 0
        assert rt.net_pnl < rt.gross_pnl
        assert rt.breakeven_move_pct > 0

    def test_breakeven(self, engine):
        """Breakeven % should be positive and reasonable."""
        trade = Trade(
            symbol="NIFTY", segment=Segment.OPTIONS,
            trade_type=TradeType.INTRADAY, side=Side.BUY,
            exchange=Exchange.NSE, price=24500.0, quantity=1,
            lot_size=75, premium=150.0, strike_price=24400.0,
        )
        be = engine.breakeven(trade)
        assert be > 0
        assert be < 10  # sanity: breakeven should be < 10% for a single lot

    def test_mtf_full(self, engine, mtf_buy):
        """MTF trade should include interest in total cost."""
        result = engine.calculate(mtf_buy)

        assert result.mtf_interest > 0
        assert abs(result.stt - 1000.0) < 0.01  # 0.1% × 10L (delivery buy)
        assert result.stamp_duty > 0  # buy side
        assert result.total_cost > result.mtf_interest  # interest + other charges


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    def test_very_small_trade(self, engine):
        """₹100 trade — costs should still compute without errors."""
        trade = Trade(
            symbol="PENNY", segment=Segment.EQUITY,
            trade_type=TradeType.INTRADAY, side=Side.SELL,
            exchange=Exchange.NSE, price=1.0, quantity=100,
        )
        result = engine.calculate(trade)
        assert result.total_cost >= 0

    def test_very_large_trade(self, engine):
        """₹10 crore trade — costs should scale correctly."""
        trade = Trade(
            symbol="RELIANCE", segment=Segment.EQUITY,
            trade_type=TradeType.DELIVERY, side=Side.BUY,
            exchange=Exchange.NSE, price=2500.0, quantity=40000,
        )
        result = engine.calculate(trade)
        # STT alone: 0.1% × 10Cr = ₹1,00,000
        assert abs(result.stt - 100000.0) < 1.0

    def test_invalid_negative_price(self):
        """Negative price should raise ValueError."""
        with pytest.raises(ValueError, match="price must be non"):
            Trade(
                symbol="X", segment=Segment.EQUITY,
                trade_type=TradeType.DELIVERY, side=Side.BUY,
                exchange=Exchange.NSE, price=-100, quantity=1,
            )

    def test_options_without_premium(self):
        """Options trade without premium should raise ValueError."""
        with pytest.raises(ValueError, match="premium is required"):
            Trade(
                symbol="NIFTY", segment=Segment.OPTIONS,
                trade_type=TradeType.INTRADAY, side=Side.SELL,
                exchange=Exchange.NSE, price=24500, quantity=1, lot_size=75,
            )

    def test_mtf_without_funding_pct(self):
        """MTF trade without funding_pct should raise ValueError."""
        with pytest.raises(ValueError, match="mtf_funding_pct is required"):
            Trade(
                symbol="X", segment=Segment.EQUITY,
                trade_type=TradeType.MTF, side=Side.BUY,
                exchange=Exchange.NSE, price=100, quantity=100,
            )

    def test_cost_breakdown_dict(self, engine, equity_delivery_buy):
        """as_dict() should have all keys and match total."""
        result = engine.calculate(equity_delivery_buy)
        d = result.as_dict()
        assert "total_cost" in d
        assert "brokerage" in d
        assert "stt" in d
        assert "mtf_interest" in d
        assert abs(d["total_cost"] - result.total_cost) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])