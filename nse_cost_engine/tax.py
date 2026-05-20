"""
GST (Goods and Services Tax) calculator.

GST at 18% is levied on services: brokerage, exchange transaction charges,
SEBI turnover fee, and IPFT.

NOT levied on: STT (direct tax) or stamp duty (state levy).

This module receives the already‑computed component amounts and returns
the GST amount.
"""

from __future__ import annotations

from typing import Dict, Any

from nse_cost_engine.config_loader import get_rate


def calculate_gst(
    brokerage: float,
    exchange_charges: float,
    sebi_fee: float,
    ipft: float,
    config: Dict[str, Any],
) -> float:
    """
    Calculate GST on the applicable service charges.

    GST = rate × (brokerage + exchange_charges + sebi_fee + ipft)

    Parameters
    ----------
    brokerage, exchange_charges, sebi_fee, ipft : float
        Already‑computed component amounts.
    config : dict

    Returns
    -------
    float
        GST amount in ₹.
    """
    rate = get_rate(config, "gst", "rate", default=0.18)
    taxable_base = brokerage + exchange_charges + sebi_fee + ipft
    return taxable_base * rate