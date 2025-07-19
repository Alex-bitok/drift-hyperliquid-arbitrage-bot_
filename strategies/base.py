from __future__ import annotations

import logging
import asyncio
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from connectors import DriftConnector, HyperliquidConnector
from execution.engine import ExecutionEngine
from storage.logger import log_event, log_opportunity


class ArbitrageStrategyBase(ABC):
    """Common functionality for arbitrage strategies."""

    def __init__(self, config: Dict[str, Any], drift: DriftConnector, hyper: HyperliquidConnector) -> None:
        self.config = config
        self.symbol = config.get("market", "")  # for logging
        self.drift_symbol = config.get("drift", {}).get("market", self.symbol)
        self.hyper_symbol = config.get("hyperliquid", {}).get("market", self.symbol)
        self.amount = float(config.get("amount", 0))
        self.max_slippage_bps = float(config.get("max_slippage_bps", 0))
        self.min_profit_usd = float(config.get("min_profit_usd", 0))
        self.fee_drift = float(config.get("fees", {}).get("drift", 0))
        self.fee_hyper = float(config.get("fees", {}).get("hyperliquid", 0))

        self.drift = drift
        self.hyper = hyper
        self.engine = ExecutionEngine(self.hyper, self.drift, config)

        self.logger = logging.getLogger(self.__class__.__name__)
        self._stop_event = threading.Event()

    @abstractmethod
    async def find_opportunity(self) -> Optional[Dict[str, Any]]:
        """Search for an arbitrage opportunity and return its parameters."""
        raise NotImplementedError

    def simulate(self, opportunity: Dict[str, Any]) -> None:
        """Log found opportunity without executing orders."""
        log_event(f"Simulated trade: {opportunity}")

    async def execute(self, opportunity: Dict[str, Any]) -> bool:
        """Execute a trade using the execution engine."""
        long_exchange = opportunity["long_exchange"]
        short_exchange = opportunity["short_exchange"]
        long_price = opportunity["long_price"]
        short_price = opportunity["short_price"]

        if long_exchange == "drift":
            # hyperliquid side corresponds to the short leg
            side_a = "sell"
            price_a = short_price
            side_b = "buy"
            price_b = long_price
        else:
            # drift side corresponds to the short leg
            side_a = "buy"
            price_a = long_price
            side_b = "sell"
            price_b = short_price

        return await self.engine.execute_pair_trade(
            self.hyper_symbol,
            self.drift_symbol,
            side_a,
            side_b,
            self.amount,
            price_a,
            price_b,
        )

    def stop(self) -> None:
        """Signal the running loop to exit."""
        self._stop_event.set()

    async def run(self, live: bool = True) -> None:
        """Continuously evaluate opportunities until stopped."""


        async def _process_once() -> None:
            opp = await self.find_opportunity()
            if not opp:
                self.logger.info("No opportunity found")
                log_event("No opportunity found")
                return

            f_drift = await self.drift.fetch_funding(self.drift_symbol)
            f_hyper = await self.hyper.fetch_funding(self.hyper_symbol)
            rate_drift = float(
                f_drift.get("last_funding_rate") or f_drift.get("funding_rate", 0)
            )
            rate_hyper = float(
                f_hyper.get("funding_rate") or f_hyper.get("last_funding_rate", 0)
            )
            rate_drift_norm = rate_drift / 1e9

            strategy_name = self.config.get("strategy", "")
            opp_type = (
                "Price Arbitrage" if strategy_name == "basis" else
                "Funding Rate Arbitrage" if strategy_name == "funding" else "Arbitrage"
            )

            log_opportunity(
                {
                    "type": opp_type,
                    "long_exchange": opp["long_exchange"],
                    "short_exchange": opp["short_exchange"],
                    "long_price": opp["long_price"],
                    "short_price": opp["short_price"],
                    "profit": opp.get("profit"),
                    "funding_rate_drift": rate_drift_norm,
                    "funding_rate_hyperliquid": rate_hyper,
                }
            )
            self.logger.info("%s: long %s @ %s short %s @ %s; potential profit %.2f; funding drift %.6f, hyperliquid %.6f",
                opp_type,
                opp["long_exchange"],
                opp["long_price"],
                opp["short_exchange"],
                opp["short_price"],
                opp.get("profit"),
                rate_drift_norm,
                rate_hyper,
            )

            if live:
                executed = await self.execute(opp)
                if executed:
                    log_event("Trade executed successfully")
                else:
                    log_event("Trade execution failed")
            else:
                self.simulate(opp)

        async def _loop() -> None:
            interval = float(self.config.get("poll_interval_sec", 1))
            while not self._stop_event.is_set():
                await _process_once()
                await asyncio.sleep(interval)

        try:
            await _loop()
        finally:
            self._stop_event.clear()
