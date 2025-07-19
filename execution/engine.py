from __future__ import annotations

import logging
import asyncio
from typing import Any, Dict, Awaitable, Callable, Optional

from connectors import ConnectorBase
from storage.logger import log_event, log_trade


class ExecutionEngine:
    """Coordinate order execution across two exchanges."""

    def __init__(self, connector_a: ConnectorBase, connector_b: ConnectorBase, config: Dict[str, Any]):
        self.connector_a = connector_a
        self.connector_b = connector_b
        self.config = config
        self.timeouts = config.get("timeouts", {})
        self.safe_mode_enabled = bool(config.get("safe_mode", False))
        self.safe_mode_triggered = False

        self.logger = logging.getLogger(self.__class__.__name__)

    async def _wait_fill(
        self,
        fetch_position: Callable[[str], Awaitable[Dict[str, Any]]],
        symbol: str,
        side: str,
        amount: float,
        initial_pos: Dict[str, Any],
    ) -> bool:
        """Wait until position reflects the filled order or timeout occurs."""
        timeout = self.timeouts.get("order_submit_sec", 10)
        loop_time = asyncio.get_running_loop().time
        end_time = loop_time() + timeout
        while loop_time() < end_time:
            try:
                pos = await fetch_position(symbol)
            except Exception as exc:  # pragma: no cover - depends on sdk
                self.logger.error("Failed to fetch position: %s", exc)
                return False

            base_amt = pos.get("base_asset_amount", 0)
            init_base = initial_pos.get("base_asset_amount", 0)
            diff = base_amt - init_base
            if side.lower() == "buy" and diff >= amount:
                return True
            if side.lower() == "sell" and diff <= -amount:
                return True
            await asyncio.sleep(1)
        return False

    async def _safe_cancel(self, connector: ConnectorBase, order_id: Any) -> None:
        """Cancel order and ignore errors."""
        try:
            await connector.cancel_order(order_id)
        except Exception as exc:  # pragma: no cover - depends on sdk
            self.logger.warning("Failed to cancel order %s: %s", order_id, exc)
            log_event(f"Failed to cancel order {order_id}: {exc}")

    def _calc_fill_price(
        self,
        before: Dict[str, Any],
        after: Dict[str, Any],
        side: str,
        amount: float,
    ) -> Optional[float]:
        """Best effort calculation of average fill price from position deltas."""
        try:
            base_before = float(before.get("base_asset_amount", 0))
            base_after = float(after.get("base_asset_amount", 0))
            quote_before = float(before.get("quote_asset_amount", 0))
            quote_after = float(after.get("quote_asset_amount", 0))
            delta_base = base_after - base_before
            delta_quote = quote_after - quote_before
            if abs(delta_base) < 1e-12:
                return None
            price = abs(delta_quote / delta_base)
            return price
        except Exception:
            pass

        # Hyperliquid style position structure
        try:
            pos_before = before.get("position", {})
            pos_after = after.get("position", {})
            size_before = float(pos_before.get("szi", 0))
            size_after = float(pos_after.get("szi", 0))
            entry_px = float(pos_after.get("entryPx", 0))
            if abs(size_after - size_before) >= amount * 0.9 and entry_px:
                return entry_px
        except Exception:
            pass

        return None

    def _check_slippage(
        self, exchange: str, planned: float, executed: Optional[float]
    ) -> None:
        """Alert if slippage exceeds configured threshold."""
        if executed is None or planned == 0:
            return
        slip = abs((executed - planned) / planned * 10000)
        max_slip = float(self.config.get("max_slippage_bps", 0))
        if slip > max_slip:
            msg = (
                "ALERT: Slippage exceeded threshold!\n"
                f"Leg: {exchange}\n"
                f"Planned price: {planned}\n"
                f"Executed price: {executed}\n"
                f"Slippage: {slip:.0f} bps (max allowed: {max_slip} bps)"
            )
            self.logger.warning(msg)
            log_event(msg)

    async def execute_pair_trade(
        self,
        symbol_a: str,
        symbol_b: str,
        side_a: str,
        side_b: str,
        amount: float,
        price_a: float,
        price_b: float,
    ) -> bool:
        """Place two orders and ensure they both fill or rollback."""
        if self.safe_mode_enabled and self.safe_mode_triggered:
            self.logger.warning("Safe mode active - refusing to place new orders")
            log_event("Safe mode active - refusing to place new orders")
            return False


        initial_a = await self.connector_a.get_position(symbol_a)
        initial_b = await self.connector_b.get_position(symbol_b)

        order_id_a = None
        order_id_b = None
        try:
            order_id_a = await self.connector_a.place_order(
                symbol_a,
                side_a,
                amount,
                price_a,
            )
            order_id_b = await self.connector_b.place_order(
                symbol_b,
                side_b,
                amount,
                price_b,
            )

            filled_a = await self._wait_fill(
                self.connector_a.get_position,
                symbol_a,
                side_a,
                amount,
                initial_a,
            )
            filled_b = await self._wait_fill(
                self.connector_b.get_position,
                symbol_b,
                side_b,
                amount,
                initial_b,
            )

            if not (filled_a and filled_b):
                raise TimeoutError("Fill timeout")

            final_a = await self.connector_a.get_position(symbol_a)
            final_b = await self.connector_b.get_position(symbol_b)

            exec_price_a = self._calc_fill_price(initial_a, final_a, side_a, amount)
            exec_price_b = self._calc_fill_price(initial_b, final_b, side_b, amount)

            log_trade(
                {
                    "symbol_a": symbol_a,
                    "symbol_b": symbol_b,
                    "side_a": side_a,
                    "side_b": side_b,
                    "amount": amount,
                    "price_a": price_a,
                    "price_b": price_b,
                    "exec_price_a": exec_price_a,
                    "exec_price_b": exec_price_b,
                }
            )

            self._check_slippage("hyperliquid", price_a, exec_price_a)
            self._check_slippage("drift", price_b, exec_price_b)

            log_event("Trade executed successfully")
            return True
        except Exception as exc:  # pragma: no cover - depends on sdk
            self.logger.error("Execution failed: %s", exc)
            log_event(f"Execution failed: {exc}")
            if order_id_a is not None:
                await self._safe_cancel(self.connector_a, order_id_a)
            if order_id_b is not None:
                await self._safe_cancel(self.connector_b, order_id_b)
            self.safe_mode_triggered = True
            return False
