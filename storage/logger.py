import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


DEFAULT_TRADE_FILE = Path("storage/trades.jsonl")
DEFAULT_EVENT_FILE = Path("storage/events.log")
DEFAULT_OPP_FILE = Path("storage/opportunities.jsonl")


def setup_logging(config: Dict[str, Any]) -> None:
    """Configure root logger from config."""
    log_cfg = config.get("logging", {})
    level_str = log_cfg.get("level", "INFO")
    level = getattr(logging, level_str.upper(), logging.INFO)
    log_file = log_cfg.get("log_file")

    handlers = [logging.StreamHandler()]
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def log_trade(trade: Dict[str, Any], file_path: Path = DEFAULT_TRADE_FILE) -> None:
    """Append executed trade info as JSON line."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"timestamp": datetime.utcnow().isoformat(), **trade}
    with file_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def log_event(message: str, file_path: Path = DEFAULT_EVENT_FILE) -> None:
    """Append event message with timestamp."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().isoformat()
    with file_path.open("a") as f:
        f.write(f"{ts} {message}\n")


def log_opportunity(
    info: Dict[str, Any], file_path: Path = DEFAULT_OPP_FILE
) -> None:
    """Append arbitrage opportunity as JSON line."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"timestamp": datetime.utcnow().isoformat(), **info}
    for key in ("funding_rate_drift", "funding_rate_hyperliquid"):
        if key in entry and isinstance(entry[key], (float, int)):
            entry[key] = format(entry[key], ".6f")
    with file_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
