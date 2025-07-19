from __future__ import annotations

from typing import Any, Dict, Optional, List

from .base import ArbitrageStrategyBase


class BasisStrategy(ArbitrageStrategyBase):
    """Price arbitrage strategy between Drift and Hyperliquid."""

    async def find_opportunity(self) -> Optional[Dict[str, Any]]:
        """Return opportunity parameters if price spread is attractive."""
        book_drift = await self.drift.fetch_book(self.drift_symbol)
        if not book_drift.get("bids") or not book_drift.get("asks"):
            return None

        book_hyper = await self.hyper.fetch_book(self.hyper_symbol)
        if not book_hyper.get("bids") or not book_hyper.get("asks"):
            return None

        bid_drift = book_drift["bids"][0]["price"]
        ask_drift = book_drift["asks"][0]["price"]
        bid_hyper = book_hyper["bids"][0]["price"]
        ask_hyper = book_hyper["asks"][0]["price"]

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
        buy_drift_slip = slippage(book_drift["asks"], self.amount)
        sell_drift_price = avg_price(book_drift["bids"], self.amount)
        sell_drift_slip = slippage(book_drift["bids"], self.amount)

        buy_hyper_price = avg_price(book_hyper["asks"], self.amount)
        buy_hyper_slip = slippage(book_hyper["asks"], self.amount)
        sell_hyper_price = avg_price(book_hyper["bids"], self.amount)
        sell_hyper_slip = slippage(book_hyper["bids"], self.amount)

        gross_drift_long = (sell_hyper_price - buy_drift_price) * self.amount
        fee_long = buy_drift_price * self.amount * self.fee_drift
        fee_short = sell_hyper_price * self.amount * self.fee_hyper
        fees_drift_long = 2 * (fee_long + fee_short)
        profit_drift_long = gross_drift_long - fees_drift_long

        gross_hyper_long = (sell_drift_price - buy_hyper_price) * self.amount
        fee_long = buy_hyper_price * self.amount * self.fee_hyper
        fee_short = sell_drift_price * self.amount * self.fee_drift
        fees_hyper_long = 2 * (fee_long + fee_short)
        profit_hyper_long = gross_hyper_long - fees_hyper_long

        worst_slip_drift_long = max(buy_drift_slip, sell_hyper_slip)
        worst_slip_hyper_long = max(buy_hyper_slip, sell_drift_slip)

        if worst_slip_drift_long > self.max_slippage_bps and worst_slip_hyper_long > self.max_slippage_bps:
            return None
        if worst_slip_drift_long > self.max_slippage_bps:
            profit_drift_long = float('-inf')
        if worst_slip_hyper_long > self.max_slippage_bps:
            profit_hyper_long = float('-inf')

        if profit_drift_long >= self.min_profit_usd and profit_drift_long >= profit_hyper_long:
            return {
                "long_exchange": "drift",
                "short_exchange": "hyperliquid",
                "long_price": buy_drift_price,
                "short_price": sell_hyper_price,
                "spread": sell_hyper_price - buy_drift_price,
                "profit": profit_drift_long,
            }
        if profit_hyper_long >= self.min_profit_usd:
            return {
                "long_exchange": "hyperliquid",
                "short_exchange": "drift",
                "long_price": buy_hyper_price,
                "short_price": sell_drift_price,
                "spread": sell_drift_price - buy_hyper_price,
                "profit": profit_hyper_long,
            }
        if profit_drift_long >= profit_hyper_long:
            price_drift = ask_drift
            price_hyper = bid_hyper
            spread = bid_hyper - ask_drift
            gross = gross_drift_long
            fees = fees_drift_long
            profit = profit_drift_long
        else:
            price_drift = bid_drift
            price_hyper = ask_hyper
            spread = bid_drift - ask_hyper
            gross = gross_hyper_long
            fees = fees_hyper_long
            profit = profit_hyper_long

        return None
