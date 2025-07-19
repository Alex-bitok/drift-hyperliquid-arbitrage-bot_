from __future__ import annotations

from pathlib import Path
import os
from typing import Optional, Any, Dict

import yaml
from pydantic import BaseModel, ConfigDict, field_validator


class DriftConfig(BaseModel):
    """Settings for Drift exchange."""

    private_key: str
    rpc_url: Optional[str] = None
    ws_url: Optional[str] = None
    sub_account_id: int = 0
    market: Optional[str] = None


class HyperliquidConfig(BaseModel):
    """Settings for Hyperliquid exchange."""

    api_key: str
    api_secret: Optional[str] = None
    account_address: Optional[str] = None
    api_url: Optional[str] = None
    market: str


class LoggingConfig(BaseModel):
    level: str = "INFO"
    log_file: Optional[str] = None


class TimeoutsConfig(BaseModel):
    order_submit_sec: int = 10
    order_cancel_sec: int = 5


class BotConfig(BaseModel):
    """Top level application configuration."""

    strategies: Dict[str, Any] = {}
    mode: str = "live"
    market: str
    amount: float = 0.0
    leverage: Optional[int] = None
    max_slippage_bps: float = 0.0
    min_profit_usd: float = 0.0
    hold_time_sec: int = 3600
    drift: DriftConfig
    hyperliquid: HyperliquidConfig
    logging: LoggingConfig = LoggingConfig()
    safe_mode: bool = False
    timeouts: TimeoutsConfig = TimeoutsConfig()

    model_config = ConfigDict(extra="allow")

    @field_validator("strategies", mode="before")
    @classmethod
    def _normalize_strategies(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(v, dict):
            out = {}
            for name, cfg in v.items():
                if isinstance(cfg, bool):
                    out[name] = {} if cfg else {"enabled": False}
                elif isinstance(cfg, dict):
                    out[name] = cfg
            return out
        return {}


class ConfigLoader:
    """Load and validate bot configuration from YAML."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> BotConfig:
        with self.path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # fallback to environment variables for sensitive fields
        drift = data.get("drift", {})
        drift.setdefault("private_key", os.getenv("DRIFT_PRIVATE_KEY"))
        data["drift"] = drift

        hyper = data.get("hyperliquid", {})
        hyper.setdefault("api_key", os.getenv("HYPERLIQUID_API_KEY"))
        hyper.setdefault("api_secret", os.getenv("HYPERLIQUID_API_SECRET"))
        data["hyperliquid"] = hyper

        return BotConfig.model_validate(data)


def load_config(path: str) -> BotConfig:
    """Load and validate configuration from YAML file."""

    loader = ConfigLoader(path)
    return loader.load()


__all__ = ["BotConfig", "ConfigLoader", "load_config"]
