"""
NSE Cost Engine — Interactive Dashboard
========================================

Streamlit-based interactive cost calculator with:
- Single trade cost calculator
- Round trip P&L analyser
- Market impact visualiser (live Dhan API data)
- Cross-broker comparison
- Breakeven calculator

Usage:
    streamlit run dashboard/app.py

Requirements:
    pip install streamlit plotly
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

from nse_cost_engine import (
    CostEngine, Trade, CostBreakdown, RoundTripResult,
    Segment, TradeType, Side, Exchange,
)


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="NSE Cost Engine",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar — Trade Input
# ---------------------------------------------------------------------------
st.sidebar.title("📊 NSE Cost Engine")
st.sidebar.markdown("---")

broker = st.sidebar.selectbox("Broker", ["dhan", "zerodha"], index=0)
engine = CostEngine(broker=broker)

st.sidebar.markdown("### Trade Parameters")

symbol = st.sidebar.text_input("Symbol", value="RELIANCE")

segment = st.sidebar.selectbox("Segment", ["Equity", "Futures", "Options", "ETF"])
segment_map = {"Equity": Segment.EQUITY, "Futures": Segment.FUTURES,
               "Options": Segment.OPTIONS, "ETF": Segment.ETF}

trade_type = st.sidebar.selectbox("Trade Type", ["Delivery", "Intraday", "MTF"])
trade_type_map = {"Delivery": TradeType.DELIVERY, "Intraday": TradeType.INTRADAY,
                  "MTF": TradeType.MTF}

side = st.sidebar.selectbox("Side", ["Buy", "Sell"])
side_map = {"Buy": Side.BUY, "Sell": Side.SELL}

exchange = st.sidebar.selectbox("Exchange", ["NSE", "BSE"])
exchange_map = {"NSE": Exchange.NSE, "BSE": Exchange.BSE}

price = None
premium = None
strike_price = None

# Show Price only for equity/ETF
if segment in ("Equity", "ETF"):
    price = st.sidebar.number_input("Price (₹)", min_value=0.01, value=2450.0, step=0.05)

# Quantity label changes for F&O
if segment in ("Futures", "Options"):
    quantity = st.sidebar.number_input("Lots", min_value=1, value=1, step=1)
    lot_size = st.sidebar.number_input("Lot Size", min_value=1, value=75, step=1)
else:
    quantity = st.sidebar.number_input("Quantity (shares)", min_value=1, value=100, step=1)
    lot_size = 1

# Options-specific fields
if segment == "Options":
    premium = st.sidebar.number_input("Premium (₹)", min_value=0.01, value=150.0, step=0.05)
    strike_price = st.sidebar.number_input("Strike Price (₹)", min_value=0.01, value=24400.0, step=0.05)
    # For options, underlying price is strike (informational)
    price = strike_price

# Futures needs a price (futures price)
if segment == "Futures":
    price = st.sidebar.number_input("Futures Price (₹)", min_value=0.01, value=24500.0, step=0.05)

# MTF fields
mtf_leverage = None
mtf_holding_days = None
if trade_type == "MTF":
    mtf_leverage = st.sidebar.number_input("Leverage (×)", min_value=1.0, max_value=10.0, value=4.0, step=0.05,
                                            help="e.g. 4.55× means broker funds ~78%, you put up ~22%")
    mtf_holding_days = st.sidebar.number_input("Holding Days", min_value=0, value=7, step=1)

# Market impact fields
st.sidebar.markdown("### Market Impact (Optional)")
daily_vol = st.sidebar.number_input("Daily Volatility (%)", min_value=0.0, value=0.0, step=0.1,
                                     help="Set to 0 to skip impact. Use 'Fetch Live Data' tab to get real values.")
avg_daily_vol = st.sidebar.number_input("Avg Daily Volume", min_value=0, value=0, step=100000)

# ---------------------------------------------------------------------------
# Build Trade object
# ---------------------------------------------------------------------------
try:
    trade_kwargs = dict(
        symbol=symbol,
        segment=segment_map[segment],
        trade_type=trade_type_map[trade_type],
        side=side_map[side],
        exchange=exchange_map[exchange],
        price=price,
        quantity=quantity,
        lot_size=lot_size,
    )
    if premium is not None:
        trade_kwargs["premium"] = premium
    if strike_price is not None:
        trade_kwargs["strike_price"] = strike_price
    if mtf_leverage is not None:
        trade_kwargs["mtf_leverage"] = mtf_leverage
    if mtf_holding_days is not None:
        trade_kwargs["mtf_holding_days"] = mtf_holding_days
    if daily_vol > 0:
        trade_kwargs["daily_volatility"] = daily_vol / 100
    if avg_daily_vol > 0:
        trade_kwargs["avg_daily_volume"] = avg_daily_vol

    trade = Trade(**trade_kwargs)
    trade_valid = True
except Exception as e:
    trade_valid = False
    trade_error = str(e)


# ---------------------------------------------------------------------------
# Main content — Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "💰 Cost Calculator", "🔄 Round Trip", "📈 Market Impact",
    "🏦 Broker Compare", "🎯 Breakeven"
])

# ═══════════════════════════════════════════════════════════════
# TAB 1: Single Trade Cost Calculator
# ═══════════════════════════════════════════════════════════════
with tab1:
    st.header("Trade Cost Calculator")

    if not trade_valid:
        st.error(f"Invalid trade: {trade_error}")
    else:
        result = engine.calculate(trade)

        # Summary metrics — use contract note rounding (what you actually pay)
        cn = result.as_contract_note_dict()
        col1, col2, col3, col4 = st.columns(4)

        # For options, show premium value (what costs are based on)
        if trade.segment == Segment.OPTIONS:
            display_value = trade.premium_value
            value_label = "Premium Value"
        else:
            display_value = trade.trade_value
            value_label = "Trade Value"

        col1.metric(value_label, f"₹{display_value:,.2f}")
        col2.metric("Total Cost", f"₹{cn['total_cost']:,.2f}")
        col3.metric("Cost %", f"{cn['total_cost'] / display_value * 100:.4f}%"
                     if display_value > 0 else "0%")
        col4.metric("Market Impact", f"₹{cn['market_impact']:,.2f}")

        st.markdown("---")

        # Detailed breakdown
        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.subheader("Cost Breakdown")
            d = result.as_contract_note_dict()
            breakdown_data = {
                "Component": [],
                "Amount (₹)": [],
            }
            for key, label in [
                ("brokerage", "Brokerage"),
                ("stt", "STT"),
                ("exchange_charges", "Exchange Charges"),
                ("sebi_fee", "SEBI Fee"),
                ("ipft", "IPFT"),
                ("stamp_duty", "Stamp Duty"),
                ("gst", "GST"),
                ("dp_charges", "DP Charges"),
                ("dp_charges_gst", "DP Charges GST"),
                ("mtf_interest", "MTF Interest"),
                ("market_impact", "Market Impact"),
            ]:
                if d[key] > 0:
                    breakdown_data["Component"].append(label)
                    breakdown_data["Amount (₹)"].append(round(d[key], 2))

            st.dataframe(breakdown_data, use_container_width=True, hide_index=True)

        with col_right:
            st.subheader("Cost Composition")
            if breakdown_data["Component"]:
                fig = go.Figure(data=[go.Pie(
                    labels=breakdown_data["Component"],
                    values=breakdown_data["Amount (₹)"],
                    hole=0.4,
                    marker_colors=px.colors.qualitative.Set2,
                )])
                fig.update_layout(height=350, margin=dict(t=20, b=20, l=20, r=20))
                st.plotly_chart(fig, use_container_width=True)

        # Contract note view
        with st.expander("📋 Contract Note View (with broker rounding)"):
            cn = result.as_contract_note_dict()
            st.json(cn)


# ═══════════════════════════════════════════════════════════════
# TAB 2: Round Trip
# ═══════════════════════════════════════════════════════════════
with tab2:
    st.header("Round Trip P&L Analyser")

    if not trade_valid:
        st.error(f"Invalid trade: {trade_error}")
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Entry (Buy)")
            buy_price = st.number_input("Buy Price (₹)", min_value=0.01, value=price, step=0.05, key="buy_p")
        with col2:
            st.subheader("Exit (Sell)")
            sell_price = st.number_input("Sell Price (₹)", min_value=0.01, value=price * 1.02, step=0.05, key="sell_p")

        if st.button("Calculate Round Trip", type="primary"):
            buy_kwargs = dict(trade_kwargs)
            buy_kwargs["side"] = Side.BUY
            buy_kwargs["price"] = buy_price

            sell_kwargs = dict(trade_kwargs)
            sell_kwargs["side"] = Side.SELL
            sell_kwargs["price"] = sell_price

            try:
                buy_trade = Trade(**buy_kwargs)
                sell_trade = Trade(**sell_kwargs)
                rt = engine.round_trip(buy_trade, sell_trade)

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Gross P&L", f"₹{rt.gross_pnl:,.2f}")
                c2.metric("Total Costs", f"₹{rt.total_costs:,.2f}")
                c3.metric("Net P&L", f"₹{rt.net_pnl:,.2f}",
                          delta=f"₹{rt.net_pnl:,.2f}",
                          delta_color="normal" if rt.net_pnl >= 0 else "inverse")
                c4.metric("Breakeven Move", f"{rt.breakeven_move_pct:.4f}%")

                st.markdown("---")

                col_b, col_s = st.columns(2)
                with col_b:
                    st.subheader("Buy Costs")
                    bd = rt.buy_costs.as_contract_note_dict()
                    st.dataframe({k: f"₹{v:.2f}" for k, v in bd.items() if v > 0},
                                use_container_width=True)
                with col_s:
                    st.subheader("Sell Costs")
                    sd = rt.sell_costs.as_contract_note_dict()
                    st.dataframe({k: f"₹{v:.2f}" for k, v in sd.items() if v > 0},
                                use_container_width=True)

                # Waterfall chart
                labels = ["Gross P&L"]
                values = [rt.gross_pnl]
                for key, label in [("brokerage", "Brokerage"), ("stt", "STT"),
                                   ("exchange_charges", "Exchange"), ("stamp_duty", "Stamp Duty"),
                                   ("gst", "GST"), ("dp_charges", "DP"), ("mtf_interest", "MTF Interest"),
                                   ("market_impact", "Impact")]:
                    total = bd.get(key, 0) + sd.get(key, 0)
                    if total > 0:
                        labels.append(label)
                        values.append(-total)

                labels.append("Net P&L")
                values.append(rt.net_pnl)

                fig = go.Figure(go.Waterfall(
                    x=labels, y=values,
                    measure=["absolute"] + ["relative"] * (len(labels) - 2) + ["total"],
                    connector={"line": {"color": "#888"}},
                    increasing={"marker": {"color": "#548235"}},
                    decreasing={"marker": {"color": "#C00000"}},
                    totals={"marker": {"color": "#2F5496"}},
                ))
                fig.update_layout(title="P&L Waterfall — From Gross to Net", height=400)
                st.plotly_chart(fig, use_container_width=True)

            except Exception as e:
                st.error(f"Error: {e}")


# ═══════════════════════════════════════════════════════════════
# TAB 3: Market Impact Visualiser
# ═══════════════════════════════════════════════════════════════
with tab3:
    st.header("Market Impact Visualiser")

    col1, col2, col3 = st.columns(3)
    with col1:
        imp_vol = st.number_input("Daily Volatility (%)", min_value=0.1, value=1.70, step=0.1, key="imp_vol")
    with col2:
        imp_adv = st.number_input("Avg Daily Volume", min_value=1000, value=20000000, step=1000000, key="imp_adv")
    with col3:
        imp_price = st.number_input("Price (₹)", min_value=0.01, value=2500.0, step=1.0, key="imp_price")

    # Fetch live data button
    st.markdown("---")
    fetch_col1, fetch_col2 = st.columns([1, 3])
    with fetch_col1:
        fetch_btn = st.button("🔄 Fetch Live Data (Dhan API)")
    with fetch_col2:
        sec_id = st.text_input("Security ID", value="2885",
                               help="Dhan security ID. RELIANCE=2885, HDFCBANK=1333, TCS=11536")

    if fetch_btn:
        try:
            from nse_cost_engine.data_feed import DhanDataFeed
            feed = DhanDataFeed()
            if feed.is_configured:
                with st.spinner("Fetching from Dhan API..."):
                    vol, adv = feed.get_impact_params(sec_id)
                    st.success(f"Fetched: Vol = {vol*100:.2f}%, Avg Volume = {adv:,}")
                    st.info("Update the fields above with these values to use them.")
            else:
                st.warning("Dhan API not configured. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
        except Exception as e:
            st.error(f"Error: {e}")

    st.markdown("---")

    if imp_vol > 0 and imp_adv > 0:
        # Generate impact curve
        sizes = [100, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000]
        reg_costs = []
        impacts = []
        totals = []

        for qty in sizes:
            t = Trade(
                symbol=symbol, segment=Segment.EQUITY,
                trade_type=TradeType.INTRADAY, side=Side.BUY,
                exchange=Exchange.NSE, price=imp_price, quantity=qty,
                daily_volatility=imp_vol / 100, avg_daily_volume=imp_adv,
            )
            r = engine.calculate(t)
            reg_costs.append(r.total_cost_without_impact)
            impacts.append(r.market_impact)
            totals.append(r.total_cost)

        # Bar chart
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Regulatory Costs", x=[f"{s:,}" for s in sizes],
                             y=reg_costs, marker_color="#2F5496"))
        fig.add_trace(go.Bar(name="Market Impact", x=[f"{s:,}" for s in sizes],
                             y=impacts, marker_color="#C00000"))
        fig.update_layout(
            title=f"Market Impact vs Regulatory — {symbol} @ ₹{imp_price:,.0f}",
            xaxis_title="Order Size (shares)", yaxis_title="Cost (₹)",
            barmode="group", height=450,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Table
        table_data = []
        for i, qty in enumerate(sizes):
            tv = qty * imp_price
            pct = (impacts[i] / reg_costs[i] * 100) if reg_costs[i] > 0 else 0
            bps = (impacts[i] / tv * 10000) if tv > 0 else 0
            table_data.append({
                "Shares": f"{qty:,}",
                "Trade Value": f"₹{tv:,.0f}",
                "Regulatory": f"₹{reg_costs[i]:,.2f}",
                "Impact": f"₹{impacts[i]:,.2f}",
                "Total": f"₹{totals[i]:,.2f}",
                "Impact/Reg": f"{pct:.0f}%",
                "Impact bps": f"{bps:.1f}",
            })
        st.dataframe(table_data, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════
# TAB 4: Broker Comparison
# ═══════════════════════════════════════════════════════════════
with tab4:
    st.header("Cross-Broker Comparison")

    if not trade_valid:
        st.error(f"Invalid trade: {trade_error}")
    else:
        brokers_to_compare = ["dhan", "zerodha"]
        results_compare = {}

        for b in brokers_to_compare:
            try:
                eng = CostEngine(broker=b)
                res = eng.calculate(trade)
                results_compare[b.title()] = res
            except Exception:
                pass

        if results_compare:
            # Summary
            cols = st.columns(len(results_compare))
            for i, (b_name, res) in enumerate(results_compare.items()):
                with cols[i]:
                    st.subheader(b_name)
                    st.metric("Total Cost", f"₹{res.total_cost:,.2f}")
                    st.metric("Brokerage", f"₹{res.brokerage:,.2f}")
                    st.metric("GST", f"₹{res.gst:,.2f}")

            # Bar chart comparison
            components = ["brokerage", "stt", "exchange_charges", "stamp_duty", "gst",
                         "dp_charges", "mtf_interest"]
            comp_labels = ["Brokerage", "STT", "Exchange", "Stamp Duty", "GST", "DP", "MTF Interest"]

            fig = go.Figure()
            for b_name, res in results_compare.items():
                d = res.as_contract_note_dict()
                fig.add_trace(go.Bar(
                    name=b_name,
                    x=comp_labels,
                    y=[d[c] for c in components],
                ))
            fig.update_layout(
                title="Cost Comparison by Component",
                yaxis_title="Amount (₹)", barmode="group", height=400,
            )
            st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════
# TAB 5: Breakeven Calculator
# ═══════════════════════════════════════════════════════════════
with tab5:
    st.header("Breakeven Calculator")

    if not trade_valid:
        st.error(f"Invalid trade: {trade_error}")
    elif trade.side != Side.BUY:
        st.info("Breakeven is calculated from the buy side. Switch to Buy in the sidebar.")
    else:
        be = engine.breakeven(trade)

        st.metric("Breakeven Price Move", f"{be:.4f}%",
                   help="Minimum price increase needed to cover all round-trip costs")

        be_price = trade.price * (1 + be / 100)
        st.metric("Breakeven Sell Price", f"₹{be_price:,.2f}")
        st.metric("Required Move", f"₹{be_price - trade.price:,.2f} per share")

        st.markdown("---")

        # Breakeven across different trade sizes
        st.subheader("Breakeven vs Order Size")
        be_sizes = [10, 50, 100, 500, 1000, 5000, 10000]
        be_values = []
        for q in be_sizes:
            t_kwargs = dict(trade_kwargs)
            t_kwargs["quantity"] = q
            t_kwargs["side"] = Side.BUY
            try:
                t = Trade(**t_kwargs)
                b = engine.breakeven(t)
                be_values.append(b)
            except Exception:
                be_values.append(0)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[f"{s:,}" for s in be_sizes], y=be_values,
            mode="lines+markers", marker=dict(color="#2F5496", size=8),
            line=dict(color="#2F5496", width=2),
        ))
        fig.update_layout(
            title=f"Breakeven Move % vs Order Size — {symbol}",
            xaxis_title="Quantity", yaxis_title="Breakeven (%)",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.caption("NSE Cost Engine v0.1.0 | Built by Dhairya Shah")