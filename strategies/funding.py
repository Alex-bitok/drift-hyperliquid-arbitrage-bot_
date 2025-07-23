from __future__ import annotations

from typing import Any, Dict, Optional, List

from .base import ArbitrageStrategyBase


class FundingStrategy(ArbitrageStrategyBase):
    """Funding rate arbitrage between Drift and Hyperliquid."""

    async def find_opportunity(self) -> Optional[Dict[str, Any]]:
        """Return opportunity parameters if funding spread is profitable."""
        try:
            f_drift = await self.drift.fetch_funding(self.drift_symbol)
            f_hyper = await self.hyper.fetch_funding(self.hyper_symbol)
        except Exception:
            return None

        book_drift = await self.drift.fetch_book(self.drift_symbol)
        book_hyper = await self.hyper.fetch_book(self.hyper_symbol)

        if not book_drift.get("bids") or not book_drift.get("asks"):
            self.logger.warning(
                "[FundingStrategy] Drift orderbook empty for %s", self.drift_symbol
            )
            return None

        if not book_hyper.get("bids") or not book_hyper.get("asks"):
            self.logger.warning(
                "[FundingStrategy] Hyperliquid orderbook empty for %s",
                self.hyper_symbol,
            )
            return None

        def avg_price(levels: List[Dict[str, float]], amount: float) -> float:
            remain = amount
            cost = 0.0
            for lvl in levels:
                size = float(lvl.get("size", amount))
                take = min(remain, size)
                cost += lvl["price"] * take
                remain -= take
                if remain <= 0:
                    break
            if remain > 0:
                cost += levels[-1]["price"] * remain
            return cost / amount

        def slippage(levels: List[Dict[str, float]], amount: float) -> float:
            best = levels[0]["price"]
            avg = avg_price(levels, amount)
            return abs((avg - best) / best * 10000)

        buy_drift_price = avg_price(book_drift["asks"], self.amount)
        sell_drift_price = avg_price(book_drift["bids"], self.amount)
        buy_drift_slip = slippage(book_drift["asks"], self.amount)
        sell_drift_slip = slippage(book_drift["bids"], self.amount)

        buy_hyper_price = avg_price(book_hyper["asks"], self.amount)
        sell_hyper_price = avg_price(book_hyper["bids"], self.amount)
        buy_hyper_slip = slippage(book_hyper["asks"], self.amount)
        sell_hyper_slip = slippage(book_hyper["bids"], self.amount)

        mid_drift = (buy_drift_price + sell_drift_price) / 2
        mid_hyper = (buy_hyper_price + sell_hyper_price) / 2

        funding_drift = await self.drift.fetch_funding(self.drift_symbol)
        funding_hyper = await self.hyper.fetch_funding(self.hyper_symbol)
        rate_drift_raw = funding_drift.get("last_funding_rate") or funding_drift.get("funding_rate", 0)
        rate_drift = float(rate_drift_raw) / 1e9  # Drift
        
        rate_hyper = float(
            funding_hyper.get("funding_rate")
            or funding_hyper.get("last_funding_rate", 0)
        )

        spread = rate_drift - rate_hyper
        avg_price = (mid_drift + mid_hyper) / 2
        hold_hours = float(self.config.get("hold_time_sec", 3600)) / 3600
        gross_profit = abs(spread) * avg_price * self.amount * hold_hours

        if spread > 0:
            long_price = book_hyper["asks"][0]["price"]
            short_price = book_drift["bids"][0]["price"]
            drift_slip = sell_drift_slip
            hyper_slip = buy_hyper_slip
            fee_rate_long = self.fee_hyper
            fee_rate_short = self.fee_drift
        else:
            long_price = book_drift["asks"][0]["price"]
            short_price = book_hyper["bids"][0]["price"]
            drift_slip = buy_drift_slip
            hyper_slip = sell_hyper_slip
            fee_rate_long = self.fee_drift
            fee_rate_short = self.fee_hyper

        fee_long = long_price * self.amount * fee_rate_long
        fee_short = short_price * self.amount * fee_rate_short
        total_fees = 2 * (fee_long + fee_short)
        profit = gross_profit - total_fees

        if profit < self.min_profit_usd:
            return None

        if drift_slip > self.max_slippage_bps or hyper_slip > self.max_slippage_bps:
            return None


        if spread > 0:
            return {
                "long_exchange": "hyperliquid",
                "short_exchange": "drift",
                "long_price": book_hyper["asks"][0]["price"],
                "short_price": book_drift["bids"][0]["price"],
                "funding_spread": spread,
                "profit": profit,
            }
        else:
            return {
                "long_exchange": "drift",
                "short_exchange": "hyperliquid",
                "long_price": book_drift["asks"][0]["price"],
                "short_price": book_hyper["bids"][0]["price"],
                "funding_spread": spread,
                "profit": profit,
            }
