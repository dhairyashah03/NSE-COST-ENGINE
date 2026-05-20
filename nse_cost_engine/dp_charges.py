"""
Depository Participant (DP) charges.

Applies ONLY on delivery sell transactions (shares debited from demat).
Charged per ISIN per day — if you sell multiple orders of the same stock
on the same day, it's one DP charge.

Returns both the base charge and the GST on DP charges separately,
since DP‑GST is accounted for differently from the main GST pool.
"""

from __future__ import annotations

from typing import Dict, Any, Tuple

from nse_cost_engine.models import Trade
from nse_cost_engine.utils import is_delivery_sell
from nse_cost_engine.config_loader import get_rate


def calculate_dp_charges(trade: Trade, config: Dict[str, Any]) -> Tuple[float, float]:
    """
    Calculate DP charges and associated GST.

    Parameters
    ----------
    trade : Trade
    config : dict

    Returns
    -------
    (dp_charge, dp_gst) : Tuple[float, float]
        Base DP charge and 18% GST on it.
        Both are 0.0 if not a delivery sell.
    """
    if not is_delivery_sell(trade):
        return 0.0, 0.0

    dp_config = config.get("dp_charges", {})
    base = float(dp_config.get("rate_per_instruction", 15.93))
    gst_applicable = dp_config.get("gst_applicable", True)

    gst_rate = get_rate(config, "gst", "rate", default=0.18) if gst_applicable else 0.0
    dp_gst = base * gst_rate

    return base, dp_gst