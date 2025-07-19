import argparse
import asyncio
import os
import certifi
from connectors import DriftConnector, HyperliquidConnector
from config import ConfigLoader
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,  # override any existing configuration
)
os.environ["SSL_CERT_FILE"] = certifi.where()

STRATEGY_CHOICES = ["basis", "funding"]


async def async_main() -> None:
    """Entry point for asynchronous CLI execution."""
    parser = argparse.ArgumentParser(description="Drift-Hyperliquid Arbitrage Bot")
    parser.add_argument("--strategy", choices=STRATEGY_CHOICES, default=None, help="Strategy to run (basis/funding)")
    parser.add_argument("--mode", choices=["live", "dry-run"], default=None, help="Execution mode override")
    parser.add_argument("--dry-run", action="store_true", help="Shortcut for --mode dry-run")
    parser.add_argument("--safe-mode", action="store_true", help="Force enable safe mode")
    parser.add_argument("--log-level", default="INFO", help="Override logging level")
    parser.add_argument("--config", required=False, default="config/main.yaml", help="Path to config YAML file")
    args = parser.parse_args()

    loader = ConfigLoader(args.config)
    cfg_model = loader.load()
    config = cfg_model.model_dump()

    drift_conn = DriftConnector(config.get("drift", {}))
    await drift_conn.async_init()

    logger = logging.getLogger(__name__)

    hyper_conn = HyperliquidConnector(config.get("hyperliquid", {}))
    if hasattr(hyper_conn, "async_init"):
        await hyper_conn.async_init()
    


    from storage.logger import setup_logging
    from strategies import STRATEGY_MAP
    from strategies.runner import MultiStrategyRunner

    if args.mode is not None:
        config["mode"] = args.mode
    if args.dry_run:
        config["mode"] = "dry-run"
    if args.safe_mode:
        config["safe_mode"] = True
    if args.log_level:
        config.setdefault("logging", {})["level"] = args.log_level

    setup_logging(config)

    strategies_cfg = config.get("strategies", {})

    def _enabled(cfg):
        return cfg if isinstance(cfg, bool) else cfg.get("enabled", True)

    enabled = [n for n, c in strategies_cfg.items() if _enabled(c)]

    if not args.strategy and len(enabled) > 1:
        runner = MultiStrategyRunner(config, drift=drift_conn, hyper=hyper_conn)
        live = config.get("mode", "live") == "live"
        await runner.run(live=live)
        return

    strategy_name = args.strategy or config.get("strategy") or (enabled[0] if enabled else None)
    if strategy_name in strategies_cfg:
        strat_cfg = strategies_cfg[strategy_name]
        if isinstance(strat_cfg, dict):
            config.update(strat_cfg)

    strategy_cls = STRATEGY_MAP[strategy_name]
    strategy = strategy_cls(config, drift=drift_conn, hyper=hyper_conn)

    live = config.get("mode", "live") == "live"
    await strategy.run(live=live)


def main() -> None:
    """Synchronous wrapper for ``async_main``."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
