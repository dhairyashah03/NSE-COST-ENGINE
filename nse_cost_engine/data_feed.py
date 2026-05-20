"""
Data feed module for the NSE Cost Engine.

Pulls historical OHLCV data from Dhan's API to compute:
- daily_volatility  (std dev of log returns over N days)
- avg_daily_volume  (mean volume over N days)

These feed directly into the market impact models (sqrt / Almgren-Chriss).

Usage:
    from nse_cost_engine.data_feed import DhanDataFeed

    feed = DhanDataFeed()  # reads credentials from .env or environment
    vol, adv = feed.get_impact_params("1333", exchange_segment="NSE_EQ")

    # Or enrich a Trade object directly:
    trade = feed.enrich_trade(trade)
    # trade.daily_volatility and trade.avg_daily_volume are now populated

Prerequisites:
    pip install requests python-dotenv

    Create a .env file (see .env.example):
        DHAN_CLIENT_ID=your_id
        DHAN_ACCESS_TOKEN=your_token

Security:
    - Credentials are read from environment variables, never hardcoded
    - .env is in .gitignore and never committed
"""

from __future__ import annotations

import os
import math
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger("nse_cost_engine.data_feed")

# ---------------------------------------------------------------------------
# Try to load .env if python-dotenv is available
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    # Look for .env in the project root (two levels up from this file)
    from pathlib import Path
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv not installed; rely on system env vars


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DHAN_BASE_URL = "https://api.dhan.co/v2"
HISTORICAL_ENDPOINT = f"{DHAN_BASE_URL}/charts/historical"
DEFAULT_LOOKBACK_DAYS = 30  # days of history for volatility computation


# ---------------------------------------------------------------------------
# DhanDataFeed
# ---------------------------------------------------------------------------

class DhanDataFeed:
    """
    Fetches market data from Dhan's Historical Data API.

    Computes:
    - daily_volatility: annualised std dev of daily log returns,
      then divided by √252 to get per-day volatility
    - avg_daily_volume: simple mean of daily volume over lookback period

    Parameters
    ----------
    client_id : str, optional
        Dhan client ID. Reads from DHAN_CLIENT_ID env var if not provided.
    access_token : str, optional
        Dhan access token. Reads from DHAN_ACCESS_TOKEN env var if not provided.
    lookback_days : int
        Number of trading days to look back for volatility/volume computation.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        access_token: Optional[str] = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ):
        self._client_id = client_id or os.environ.get("DHAN_CLIENT_ID", "")
        self._access_token = access_token or os.environ.get("DHAN_ACCESS_TOKEN", "")
        self._lookback_days = lookback_days

        if not self._access_token:
            logger.warning(
                "No Dhan access token found. Set DHAN_ACCESS_TOKEN in .env "
                "or pass access_token to DhanDataFeed(). "
                "Market impact will return 0."
            )

    @property
    def is_configured(self) -> bool:
        """Check if API credentials are available."""
        return bool(self._access_token)

    def fetch_daily_ohlcv(
        self,
        security_id: str,
        exchange_segment: str = "NSE_EQ",
        instrument: str = "EQUITY",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, list]:
        """
        Fetch daily OHLCV data from Dhan's Historical Data API.

        Parameters
        ----------
        security_id : str
            Dhan's security ID (e.g., "1333" for HDFC Bank).
            Find IDs at: https://dhanhq.co/docs/v2/instruments/
        exchange_segment : str
            "NSE_EQ", "BSE_EQ", "NSE_FNO", etc.
        instrument : str
            "EQUITY", "FUTIDX", "OPTIDX", "FUTSTK", "OPTSTK", etc.
        from_date : str, optional
            Start date (YYYY-MM-DD). Defaults to lookback_days ago.
        to_date : str, optional
            End date (YYYY-MM-DD). Defaults to today.

        Returns
        -------
        dict
            {"open": [...], "high": [...], "low": [...],
             "close": [...], "volume": [...], "timestamp": [...]}

        Raises
        ------
        ConnectionError
            If the API call fails.
        ValueError
            If credentials are missing.
        """
        if not self.is_configured:
            raise ValueError(
                "Dhan API credentials not configured. "
                "Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env"
            )

        try:
            import requests
        except ImportError:
            raise ImportError(
                "requests library required for DhanDataFeed. "
                "Install with: pip install requests"
            )

        if to_date is None:
            to_date = datetime.now().strftime("%Y-%m-%d")
        if from_date is None:
            from_dt = datetime.now() - timedelta(days=int(self._lookback_days * 1.5))
            from_date = from_dt.strftime("%Y-%m-%d")

        payload = {
            "securityId": security_id,
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "expiryCode": 0,
            "oi": False,
            "fromDate": from_date,
            "toDate": to_date,
        }

        headers = {
            "Content-Type": "application/json",
            "access-token": self._access_token,
        }

        logger.info(
            "Fetching OHLCV | security=%s | segment=%s | %s to %s",
            security_id, exchange_segment, from_date, to_date,
        )

        response = requests.post(
            HISTORICAL_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=10,
        )

        if response.status_code != 200:
            raise ConnectionError(
                f"Dhan API error {response.status_code}: {response.text[:200]}"
            )

        data = response.json()

        if "close" not in data or not data["close"]:
            raise ValueError(
                f"No data returned for security {security_id}. "
                f"Check the security ID and exchange segment."
            )

        return data

    def compute_volatility_and_volume(
        self,
        ohlcv: Dict[str, list],
        lookback: Optional[int] = None,
    ) -> Tuple[float, int]:
        """
        Compute daily volatility and average daily volume from OHLCV data.

        Parameters
        ----------
        ohlcv : dict
            Output from fetch_daily_ohlcv().
        lookback : int, optional
            Number of most recent days to use. Defaults to self._lookback_days.

        Returns
        -------
        (daily_volatility, avg_daily_volume) : Tuple[float, int]
            daily_volatility: std dev of daily log returns (not annualised)
            avg_daily_volume: mean daily volume as integer
        """
        lookback = lookback or self._lookback_days

        closes = ohlcv["close"]
        volumes = ohlcv["volume"]

        # Use the most recent `lookback` days
        closes = closes[-lookback:] if len(closes) > lookback else closes
        volumes = volumes[-lookback:] if len(volumes) > lookback else volumes

        if len(closes) < 2:
            logger.warning("Not enough data points (%d) for volatility", len(closes))
            return 0.0, 0

        # Daily log returns
        log_returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0 and closes[i] > 0:
                log_returns.append(math.log(closes[i] / closes[i - 1]))

        if not log_returns:
            return 0.0, 0

        # Standard deviation of daily log returns
        mean_ret = sum(log_returns) / len(log_returns)
        variance = sum((r - mean_ret) ** 2 for r in log_returns) / (len(log_returns) - 1)
        daily_vol = math.sqrt(variance)

        # Average daily volume
        avg_vol = int(sum(volumes) / len(volumes)) if volumes else 0

        logger.info(
            "Computed | daily_vol=%.4f | avg_volume=%d | data_points=%d",
            daily_vol, avg_vol, len(closes),
        )

        return daily_vol, avg_vol

    def get_impact_params(
        self,
        security_id: str,
        exchange_segment: str = "NSE_EQ",
        instrument: str = "EQUITY",
    ) -> Tuple[float, int]:
        """
        One-call convenience: fetch data and compute impact parameters.

        Parameters
        ----------
        security_id : str
            Dhan security ID.
        exchange_segment : str
        instrument : str

        Returns
        -------
        (daily_volatility, avg_daily_volume) : Tuple[float, int]
        """
        ohlcv = self.fetch_daily_ohlcv(
            security_id=security_id,
            exchange_segment=exchange_segment,
            instrument=instrument,
        )
        return self.compute_volatility_and_volume(ohlcv)

    def enrich_trade(
        self,
        trade,
        security_id: str,
        exchange_segment: str = "NSE_EQ",
        instrument: str = "EQUITY",
    ):
        """
        Populate a Trade object's volatility and volume fields from live data.

        Parameters
        ----------
        trade : Trade
            The trade to enrich. Modified in place.
        security_id : str
            Dhan security ID for this instrument.
        exchange_segment : str
        instrument : str

        Returns
        -------
        Trade
            The same trade object, with daily_volatility and avg_daily_volume set.
        """
        if not self.is_configured:
            logger.warning("Dhan API not configured; skipping trade enrichment")
            return trade

        try:
            vol, adv = self.get_impact_params(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument=instrument,
            )
            trade.daily_volatility = vol
            trade.avg_daily_volume = adv
            logger.info(
                "Enriched trade %s | vol=%.4f | adv=%d",
                trade.symbol, vol, adv,
            )
        except Exception as e:
            logger.error("Failed to enrich trade %s: %s", trade.symbol, e)

        return trade


# ---------------------------------------------------------------------------
# Security ID lookup helpers
# ---------------------------------------------------------------------------

# Common security IDs for quick reference.
# Full list: https://dhanhq.co/docs/v2/instruments/
# Download CSV: https://images.dhan.co/api-data/api-scrip-master.csv

COMMON_SECURITY_IDS = {
    "RELIANCE": "2885",
    "HDFCBANK": "1333",
    "TCS": "11536",
    "INFY": "1594",
    "ICICIBANK": "4963",
    "SBIN": "3045",
    "BHARTIARTL": "10604",
    "ITC": "1660",
    "KOTAKBANK": "1922",
    "LT": "11483",
    "AXISBANK": "5900",
    "BAJFINANCE": "317",
    "MARUTI": "10999",
    "TATAMOTORS": "3456",
    "TATASTEEL": "3499",
    "WIPRO": "3787",
    "HCLTECH": "7229",
    "SUNPHARMA": "3351",
    "TITAN": "3506",
    "ADANIENT": "25",
    "NIFTY": "13",       # Index — use NSE_FNO segment
    "BANKNIFTY": "25",   # Index — use NSE_FNO segment
    "DELHIVERY": "20413",
    "PNBHOUSING": "21808",
}


def get_security_id(symbol: str) -> Optional[str]:
    """
    Look up a common security ID by symbol name.

    For a complete mapping, download:
    https://images.dhan.co/api-data/api-scrip-master.csv
    """
    return COMMON_SECURITY_IDS.get(symbol.upper())