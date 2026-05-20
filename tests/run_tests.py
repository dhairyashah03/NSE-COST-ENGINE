"""
Standalone test runner — no pytest needed.
Uses Python's built-in unittest framework.
"""

import sys
import os
import math
import unittest
import traceback

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
# Helpers
# ============================================================================

def dhan_config():
    return load_config(broker="dhan")

def engine():
    return CostEngine(broker="dhan")

def eq_delivery_buy():
    return Trade(
        symbol="RELIANCE", segment=Segment.EQUITY,
        trade_type=TradeType.DELIVERY, side=Side.BUY,
        exchange=Exchange.NSE, price=2450.0, quantity=100,
    )

def eq_delivery_sell():
    return Trade(
        symbol="RELIANCE", segment=Segment.EQUITY,
        trade_type=TradeType.DELIVERY, side=Side.SELL,
        exchange=Exchange.NSE, price=2500.0, quantity=100,
    )

def eq_intraday_sell():
    return Trade(
        symbol="TCS", segment=Segment.EQUITY,
        trade_type=TradeType.INTRADAY, side=Side.SELL,
        exchange=Exchange.NSE, price=3800.0, quantity=200,
    )

def nifty_fut_sell():
    return Trade(
        symbol="NIFTY", segment=Segment.FUTURES,
        trade_type=TradeType.INTRADAY, side=Side.SELL,
        exchange=Exchange.NSE, price=24500.0, quantity=1, lot_size=75,
    )

def nifty_opt_sell():
    return Trade(
        symbol="NIFTY", segment=Segment.OPTIONS,
        trade_type=TradeType.INTRADAY, side=Side.SELL,
        exchange=Exchange.NSE, price=24500.0, quantity=1, lot_size=75,
        premium=150.0, strike_price=24400.0,
    )

def nifty_opt_exercise():
    return Trade(
        symbol="NIFTY", segment=Segment.OPTIONS,
        trade_type=TradeType.INTRADAY, side=Side.SELL,
        exchange=Exchange.NSE, price=24500.0, quantity=1, lot_size=75,
        premium=150.0, strike_price=24000.0,
        settlement_price=24500.0, is_exercise=True,
    )

def mtf_buy_trade():
    return Trade(
        symbol="HDFCBANK", segment=Segment.EQUITY,
        trade_type=TradeType.MTF, side=Side.BUY,
        exchange=Exchange.NSE, price=1600.0, quantity=625,
        mtf_leverage=4.0, mtf_holding_days=7,
    )


# ============================================================================
# Tests
# ============================================================================

class TestBrokerage(unittest.TestCase):
    def setUp(self):
        self.cfg = dhan_config()

    def test_zero_delivery(self):
        r = calculate_brokerage(eq_delivery_buy(), self.cfg)
        self.assertEqual(r, 0.0)

    def test_flat_futures(self):
        r = calculate_brokerage(nifty_fut_sell(), self.cfg)
        self.assertEqual(r, 20.0)

    def test_flat_options(self):
        r = calculate_brokerage(nifty_opt_sell(), self.cfg)
        self.assertEqual(r, 20.0)

    def test_min_of_small_trade(self):
        t = Trade(symbol="IDEA", segment=Segment.EQUITY,
                  trade_type=TradeType.INTRADAY, side=Side.BUY,
                  exchange=Exchange.NSE, price=10.0, quantity=100)
        r = calculate_brokerage(t, self.cfg)
        self.assertAlmostEqual(r, 0.30, places=2)

    def test_min_of_large_trade(self):
        t = Trade(symbol="RELIANCE", segment=Segment.EQUITY,
                  trade_type=TradeType.INTRADAY, side=Side.BUY,
                  exchange=Exchange.NSE, price=2450.0, quantity=500)
        r = calculate_brokerage(t, self.cfg)
        self.assertEqual(r, 20.0)


class TestSTT(unittest.TestCase):
    def setUp(self):
        self.cfg = dhan_config()

    def test_delivery_buy(self):
        r = calculate_stt(eq_delivery_buy(), self.cfg)
        self.assertAlmostEqual(r, 245.0, places=2)

    def test_delivery_sell(self):
        r = calculate_stt(eq_delivery_sell(), self.cfg)
        self.assertAlmostEqual(r, 250.0, places=2)

    def test_intraday_buy_zero(self):
        t = Trade(symbol="TCS", segment=Segment.EQUITY,
                  trade_type=TradeType.INTRADAY, side=Side.BUY,
                  exchange=Exchange.NSE, price=3800.0, quantity=200)
        r = calculate_stt(t, self.cfg)
        self.assertEqual(r, 0.0)

    def test_intraday_sell(self):
        r = calculate_stt(eq_intraday_sell(), self.cfg)
        self.assertAlmostEqual(r, 190.0, places=2)

    def test_futures_sell(self):
        r = calculate_stt(nifty_fut_sell(), self.cfg)
        self.assertAlmostEqual(r, 918.75, places=2)

    def test_options_sell_on_premium(self):
        r = calculate_stt(nifty_opt_sell(), self.cfg)
        self.assertAlmostEqual(r, 16.875, places=3)

    def test_options_exercise_on_intrinsic(self):
        r = calculate_stt(nifty_opt_exercise(), self.cfg)
        # intrinsic = |24500 - 24000| × 75 = 37,500
        self.assertAlmostEqual(r, 56.25, places=2)


class TestExchangeCharges(unittest.TestCase):
    def setUp(self):
        self.cfg = dhan_config()

    def test_nse_equity(self):
        r = calculate_exchange_charges(eq_delivery_buy(), self.cfg)
        expected = 245000.0 * 0.000030699
        self.assertAlmostEqual(r, expected, places=2)

    def test_nse_futures(self):
        r = calculate_exchange_charges(nifty_fut_sell(), self.cfg)
        expected = 24500.0 * 75 * 0.000018299
        self.assertAlmostEqual(r, expected, delta=0.1)

    def test_nse_options_on_premium(self):
        r = calculate_exchange_charges(nifty_opt_sell(), self.cfg)
        expected = 150.0 * 75 * 0.000355299
        self.assertAlmostEqual(r, expected, places=2)


class TestSEBIandIPFT(unittest.TestCase):
    def setUp(self):
        self.cfg = dhan_config()

    def test_sebi_fee(self):
        r = calculate_sebi_fee(eq_delivery_buy(), self.cfg)
        self.assertAlmostEqual(r, 245000.0 * 0.000001, places=3)

    def test_ipft(self):
        r = calculate_ipft(eq_delivery_buy(), self.cfg)
        self.assertAlmostEqual(r, 245000.0 * 0.000000001, delta=0.0001)


class TestStampDuty(unittest.TestCase):
    def setUp(self):
        self.cfg = dhan_config()

    def test_sell_zero(self):
        r = calculate_stamp_duty(eq_delivery_sell(), self.cfg)
        self.assertEqual(r, 0.0)

    def test_delivery_buy(self):
        r = calculate_stamp_duty(eq_delivery_buy(), self.cfg)
        self.assertAlmostEqual(r, 36.75, places=2)

    def test_futures_buy(self):
        t = Trade(symbol="NIFTY", segment=Segment.FUTURES,
                  trade_type=TradeType.INTRADAY, side=Side.BUY,
                  exchange=Exchange.NSE, price=24500.0, quantity=1, lot_size=75)
        r = calculate_stamp_duty(t, self.cfg)
        self.assertAlmostEqual(r, 24500.0 * 75 * 0.00002, places=2)

    def test_options_buy_on_premium(self):
        t = Trade(symbol="NIFTY", segment=Segment.OPTIONS,
                  trade_type=TradeType.INTRADAY, side=Side.BUY,
                  exchange=Exchange.NSE, price=24500.0, quantity=1,
                  lot_size=75, premium=150.0, strike_price=24400.0)
        r = calculate_stamp_duty(t, self.cfg)
        # 150 × 75 × 0.00003 = ₹0.3375 (raw, before contract note rounding)
        self.assertAlmostEqual(r, 0.3375, places=3)


class TestGST(unittest.TestCase):
    def setUp(self):
        self.cfg = dhan_config()

    def test_gst_calculation(self):
        r = calculate_gst(20.0, 5.0, 0.5, 0.001, self.cfg)
        expected = 0.18 * (20.0 + 5.0 + 0.5 + 0.001)
        self.assertAlmostEqual(r, expected, places=3)

    def test_gst_zero_brokerage(self):
        r = calculate_gst(0.0, 7.5, 0.25, 0.0002, self.cfg)
        expected = 0.18 * (7.5 + 0.25 + 0.0002)
        self.assertAlmostEqual(r, expected, places=3)


class TestDPCharges(unittest.TestCase):
    def setUp(self):
        self.cfg = dhan_config()

    def test_delivery_sell(self):
        base, gst = calculate_dp_charges(eq_delivery_sell(), self.cfg)
        self.assertAlmostEqual(base, 12.50, places=2)
        self.assertAlmostEqual(gst, 2.25, places=2)

    def test_no_dp_buy(self):
        base, gst = calculate_dp_charges(eq_delivery_buy(), self.cfg)
        self.assertEqual(base, 0.0)

    def test_no_dp_intraday(self):
        base, gst = calculate_dp_charges(eq_intraday_sell(), self.cfg)
        self.assertEqual(base, 0.0)

    def test_no_dp_fno(self):
        base, gst = calculate_dp_charges(nifty_fut_sell(), self.cfg)
        self.assertEqual(base, 0.0)


class TestMTFInterest(unittest.TestCase):
    def setUp(self):
        self.cfg = dhan_config()

    def test_basic(self):
        t = mtf_buy_trade()
        r = calculate_mtf_interest(t, self.cfg)
        # funded = 1600 × 625 × 0.75 = 750,000 → slab 2 → 13.49%
        expected = 750000 * 0.1349 / 365 * 7
        self.assertAlmostEqual(r, expected, delta=0.1)

    def test_zero_days(self):
        t = Trade(symbol="X", segment=Segment.EQUITY,
                  trade_type=TradeType.MTF, side=Side.BUY,
                  exchange=Exchange.NSE, price=1600.0, quantity=625,
                  mtf_leverage=4.0, mtf_holding_days=0)
        self.assertEqual(calculate_mtf_interest(t, self.cfg), 0.0)

    def test_non_mtf(self):
        self.assertEqual(calculate_mtf_interest(eq_delivery_buy(), self.cfg), 0.0)

    def test_sell_side_no_interest(self):
        """MTF sell should have zero interest (interest only on buy)."""
        t = Trade(symbol="HDFCBANK", segment=Segment.EQUITY,
                  trade_type=TradeType.MTF, side=Side.SELL,
                  exchange=Exchange.NSE, price=1600.0, quantity=625,
                  mtf_leverage=4.0, mtf_holding_days=7)
        self.assertEqual(calculate_mtf_interest(t, self.cfg), 0.0)

    def test_slab1_boundary(self):
        """funded exactly ₹5L → slab 1 (12.49%)."""
        # need funded = 500000 exactly → qty * price * 0.75 = 500000
        # price=100, qty=6667 → funded = 6667*100*0.75 = 500025 (just over → slab 2)
        # price=1000, qty=667 → funded = 667*1000*0.75 = 500250 (slab 2)
        # To hit slab 1: price=100, qty=6666 → funded = 499950 (under 5L)
        t = Trade(symbol="X", segment=Segment.EQUITY,
                  trade_type=TradeType.MTF, side=Side.BUY,
                  exchange=Exchange.NSE, price=100.0, quantity=6666,
                  mtf_leverage=4.0, mtf_holding_days=1)
        r = calculate_mtf_interest(t, self.cfg)
        funded = 6666 * 100 * 0.75  # 499950
        expected = funded * 0.1249 / 365
        self.assertAlmostEqual(r, expected, delta=0.1)

    def test_highest_slab(self):
        """₹60L funded → slab 5 (16.49%)."""
        t = Trade(symbol="X", segment=Segment.EQUITY,
                  trade_type=TradeType.MTF, side=Side.BUY,
                  exchange=Exchange.NSE, price=1000.0, quantity=8000,
                  mtf_leverage=4.0, mtf_holding_days=1)
        r = calculate_mtf_interest(t, self.cfg)
        expected = 6000000 * 0.1649 / 365
        self.assertAlmostEqual(r, expected, delta=0.1)


class TestMarketImpact(unittest.TestCase):
    def setUp(self):
        self.cfg = dhan_config()

    def test_sqrt_model(self):
        t = Trade(symbol="RELIANCE", segment=Segment.EQUITY,
                  trade_type=TradeType.INTRADAY, side=Side.BUY,
                  exchange=Exchange.NSE, price=2450.0, quantity=10000,
                  daily_volatility=0.02, avg_daily_volume=5000000)
        r = calculate_market_impact(t, self.cfg, model="sqrt")
        participation = 10000 / 5000000
        expected = 0.02 * math.sqrt(participation) * 0.3 * 2450 * 10000
        self.assertAlmostEqual(r, expected, places=2)

    def test_no_data(self):
        r = calculate_market_impact(eq_delivery_buy(), self.cfg)
        self.assertEqual(r, 0.0)


class TestEngineIntegration(unittest.TestCase):
    def setUp(self):
        self.eng = engine()

    def test_delivery_buy_full(self):
        r = self.eng.calculate(eq_delivery_buy())
        self.assertAlmostEqual(r.brokerage, 0.0, places=2)
        self.assertAlmostEqual(r.stt, 245.0, places=2)
        self.assertAlmostEqual(r.stamp_duty, 36.75, places=2)
        self.assertEqual(r.dp_charges, 0.0)
        self.assertEqual(r.mtf_interest, 0.0)
        self.assertGreater(r.total_cost, 289)

    def test_delivery_sell_full(self):
        r = self.eng.calculate(eq_delivery_sell())
        self.assertAlmostEqual(r.stt, 250.0, places=2)
        self.assertAlmostEqual(r.dp_charges, 12.50, places=2)
        self.assertAlmostEqual(r.dp_charges_gst, 2.25, places=2)
        self.assertEqual(r.stamp_duty, 0.0)

    def test_options_sell_full(self):
        r = self.eng.calculate(nifty_opt_sell())
        self.assertAlmostEqual(r.brokerage, 20.0, places=2)
        self.assertAlmostEqual(r.stt, 16.875, places=3)
        self.assertEqual(r.stamp_duty, 0.0)
        self.assertEqual(r.dp_charges, 0.0)

    def test_round_trip(self):
        buy = Trade(symbol="RELIANCE", segment=Segment.EQUITY,
                    trade_type=TradeType.DELIVERY, side=Side.BUY,
                    exchange=Exchange.NSE, price=2450.0, quantity=100)
        sell = Trade(symbol="RELIANCE", segment=Segment.EQUITY,
                     trade_type=TradeType.DELIVERY, side=Side.SELL,
                     exchange=Exchange.NSE, price=2500.0, quantity=100)
        rt = self.eng.round_trip(buy, sell)
        self.assertAlmostEqual(rt.gross_pnl, 5000.0, places=2)
        self.assertGreater(rt.total_costs, 0)
        self.assertLess(rt.net_pnl, rt.gross_pnl)
        self.assertGreater(rt.breakeven_move_pct, 0)

    def test_breakeven(self):
        t = Trade(symbol="NIFTY", segment=Segment.OPTIONS,
                  trade_type=TradeType.INTRADAY, side=Side.BUY,
                  exchange=Exchange.NSE, price=24500.0, quantity=1,
                  lot_size=75, premium=150.0, strike_price=24400.0)
        be = self.eng.breakeven(t)
        self.assertGreater(be, 0)
        self.assertLess(be, 10)

    def test_mtf_full(self):
        r = self.eng.calculate(mtf_buy_trade())
        self.assertGreater(r.mtf_interest, 0)
        self.assertAlmostEqual(r.stt, 1000.0, places=2)
        self.assertGreater(r.stamp_duty, 0)
        self.assertGreater(r.total_cost, r.mtf_interest)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.eng = engine()

    def test_very_small_trade(self):
        t = Trade(symbol="PENNY", segment=Segment.EQUITY,
                  trade_type=TradeType.INTRADAY, side=Side.SELL,
                  exchange=Exchange.NSE, price=1.0, quantity=100)
        r = self.eng.calculate(t)
        self.assertGreaterEqual(r.total_cost, 0)

    def test_very_large_trade(self):
        t = Trade(symbol="RELIANCE", segment=Segment.EQUITY,
                  trade_type=TradeType.DELIVERY, side=Side.BUY,
                  exchange=Exchange.NSE, price=2500.0, quantity=40000)
        r = self.eng.calculate(t)
        self.assertAlmostEqual(r.stt, 100000.0, delta=1.0)

    def test_negative_price_raises(self):
        with self.assertRaises(ValueError):
            Trade(symbol="X", segment=Segment.EQUITY,
                  trade_type=TradeType.DELIVERY, side=Side.BUY,
                  exchange=Exchange.NSE, price=-100, quantity=1)

    def test_options_no_premium_raises(self):
        with self.assertRaises(ValueError):
            Trade(symbol="NIFTY", segment=Segment.OPTIONS,
                  trade_type=TradeType.INTRADAY, side=Side.SELL,
                  exchange=Exchange.NSE, price=24500, quantity=1, lot_size=75)

    def test_mtf_no_leverage_raises(self):
        with self.assertRaises(ValueError):
            Trade(symbol="X", segment=Segment.EQUITY,
                  trade_type=TradeType.MTF, side=Side.BUY,
                  exchange=Exchange.NSE, price=100, quantity=100)

    def test_as_dict_keys(self):
        r = self.eng.calculate(eq_delivery_buy())
        d = r.as_dict()
        for key in ["brokerage", "stt", "exchange_charges", "sebi_fee",
                     "ipft", "stamp_duty", "gst", "dp_charges",
                     "dp_charges_gst", "mtf_interest", "market_impact",
                     "total_regulatory", "total_cost"]:
            self.assertIn(key, d)


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)