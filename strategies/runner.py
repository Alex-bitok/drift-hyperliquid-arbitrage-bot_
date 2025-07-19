from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from connectors import DriftConnector, HyperliquidConnector

from . import STRATEGY_MAP


class MultiStrategyRunner:
    """Run multiple strategies concurrently."""

    def __init__(self, config: Dict[str, Any], drift: DriftConnector, hyper: HyperliquidConnector) -> None:
        self.config = config
        self.drift = drift
        self.hyper = hyper
        self.strategies: List[Any] = []
        self._init_strategies()

    def _init_strategies(self) -> None:
        strategies_cfg = self.config.get("strategies", {})
        for name, cfg in strategies_cfg.items():
            if isinstance(cfg, bool):
                if not cfg:
                    continue
                cfg = {}
            elif not cfg.get("enabled", True):
                continue
            strat_cls = STRATEGY_MAP.get(name)
            if strat_cls is None:
                continue
            merged = {**self.config, **cfg}
            merged["strategy"] = name
            self.strategies.append(strat_cls(merged, drift=self.drift, hyper=self.hyper))

    async def run(self, live: bool = True) -> None:
        await asyncio.gather(*(s.run(live=live) for s in self.strategies))
