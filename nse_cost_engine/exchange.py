"""
Exchange transaction charges.

NSE and BSE charge different rates, and the rates differ by segment.
For options, the charge is on premium_value, not notional.

BSE has a special case: different rates for index options vs stock options.
We handle this with a fallback chain in the config lookup.
"""

from __future__ import annotations

from typing import Dict, Any

from nse_cost_engine.models import Trade, Segment, Exchange
from nse_cost_engine.utils import get_turnover_base
from nse_cost_engine.config_loader import get_rate


def calculate_exchange_charges(trade: Trade, config: Dict[str, Any]) -> float:
    """
    Calculate exchange transaction charges.

    Parameters
    ----------
    trade : Trade
    config : dict
        Must contain 'exchange_charges' with sub‑keys per exchange.

    Returns
    -------
    float
        Exchange charge in ₹.
    """
    exchange = trade.exchange.value  # 'nse' or 'bse'
    segment = trade.segment.value    # 'equity', 'futures', 'options', 'etf'

    # --- Rate lookup --------------------------------------------------------
    # Try exact key first, then fallback
    rate = get_rate(config, "exchange_charges", exchange, segment)

    # BSE options have separate rates for index vs stock options
    # For now, default to the general 'options' key; can be extended
    # with an 'option_type' field on Trade if needed.
    if rate == 0.0 and segment == "options" and exchange == "bse":
        # Try index first (more common for retail)
        rate = get_rate(config, "exchange_charges", "bse", "options_index")

    # --- Base amount --------------------------------------------------------
    base = get_turnover_base(trade)

    return base * rate