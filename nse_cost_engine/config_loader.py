"""
Configuration loader for the NSE Cost Engine.

Loads rates from YAML files and merges broker‑specific profiles on top
of the default rate schedule. Every number the engine uses comes through
here — no module hardcodes any rate.

Design decisions:
- We use PyYAML (standard, zero‑dependency) for parsing.
- Config is returned as a plain dict, not a custom class. This keeps
  things simple and means the config can be trivially serialised / logged.
- Broker profiles override only the keys they define; everything else
  falls through to defaults.
"""

from __future__ import annotations

import os
import copy
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# Default paths relative to the package root
_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _PACKAGE_DIR / "config" / "default_rates.yaml"
_BROKER_DIR = _PACKAGE_DIR / "config" / "broker_profiles"


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """
    Recursively merge `override` into `base`.
    override values take priority; base is not mutated.
    """
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load and parse a single YAML file."""
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")
    return data


def load_config(
    broker: str = "dhan",
    config_path: Optional[str] = None,
    broker_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Load the full configuration: default rates + broker profile.

    Parameters
    ----------
    broker : str
        Name of the broker profile (without .yaml extension).
        Must match a file in config/broker_profiles/.
    config_path : str, optional
        Override path to the default rates YAML.
    broker_path : str, optional
        Override path to the broker profile YAML.

    Returns
    -------
    dict
        Merged configuration ready for use by calculator modules.
    """
    # --- Load default rates -------------------------------------------------
    default_path = Path(config_path) if config_path else _DEFAULT_CONFIG
    if not default_path.exists():
        raise FileNotFoundError(f"Default config not found: {default_path}")
    config = load_yaml(default_path)

    # --- Load and merge broker profile -------------------------------------
    bp = Path(broker_path) if broker_path else _BROKER_DIR / f"{broker}.yaml"
    if not bp.exists():
        raise FileNotFoundError(
            f"Broker profile '{broker}' not found at {bp}. "
            f"Available: {[f.stem for f in _BROKER_DIR.glob('*.yaml')]}"
        )
    broker_config = load_yaml(bp)
    config = _deep_merge(config, broker_config)
    config["_broker_name"] = broker_config.get("broker_name", broker)

    return config


def get_rate(config: Dict, *keys: str, default: float = 0.0) -> float:
    """
    Safely navigate nested config keys and return a numeric rate.

    Usage:
        get_rate(config, 'stt', 'equity_delivery', 'rate')
        get_rate(config, 'exchange_charges', 'nse', 'equity')
    """
    node: Any = config
    for key in keys:
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return default
    if node is None:
        return default
    return float(node)