import asyncio
import logging

logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
from typing import Any, Dict

try:  # pragma: no cover - optional heavy deps
    from eth_account import Account
    from hyperliquid.info import Info
    from hyperliquid.exchange import Exchange
except Exception:  # pragma: no cover - modules may be missing during tests
    Account = Info = Exchange = None  # type: ignore

from .base import ConnectorBase

class HyperliquidConnector(ConnectorBase):
    """Connector implementation using Hyperliquid SDK."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_url = config.get("api_url")
        self.account_address = config.get("account_address")
        self._account = Account.from_key(config["api_key"]) if Account else None
        self.info = Info(base_url=self.api_url, skip_ws=True) if Info else None
        self.exchange = (
            Exchange(self._account, base_url=self.api_url, account_address=self.account_address)
            if Exchange
            else None
        )
        self._logger = logging.getLogger(__name__)
        self.ws_error_reported = False

    async def async_init(self) -> None:
        """Initialize the connector ensuring API connectivity."""
        if self.info is None:
            raise ImportError("hyperliquid package is required")
        try:
            result = self.info.meta_and_asset_ctxs()
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=5)
            else:
                _ = result
            if self.ws_error_reported:
                self._logger.info("Reconnected to Hyperliquid")
                self.ws_error_reported = False
            self._logger.info(
                "HyperliquidConnector initialized and connected to %s", self.api_url
            )
        except Exception as exc:
            if not self.ws_error_reported:
                self._logger.warning("Hyperliquid WebSocket disconnected")
                self.ws_error_reported = True
            self._logger.error("[HyperliquidConnector] Initialization FAILED: %s", exc)
            raise


    async def fetch_book(self, symbol: str) -> Dict[str, Any]:
        """Return best bid and ask using the Info API."""
        meta, ctxs = self.info.meta_and_asset_ctxs()   # type: ignore[operator]
        idx = next(
            (i for i, asset in enumerate(meta["universe"]) if asset["name"] == symbol),
            None,
        )
        if idx is None:
            return {"bids": [], "asks": []}
        ctx = ctxs[idx]
        bid, ask = ctx.get("impactPxs", [0, 0])
        return {
            "bids": [{"price": float(bid), "size": 0}],
            "asks": [{"price": float(ask), "size": 0}],
        }

    async def fetch_funding(self, symbol: str) -> Dict[str, Any]:
        """Return current funding information from Info API."""
        meta, ctxs = self.info.meta_and_asset_ctxs()   # type: ignore[operator]
        idx = next(
            (i for i, asset in enumerate(meta["universe"]) if asset["name"] == symbol),
            None,
        )
        if idx is None:
            return {}
        ctx = ctxs[idx]
        return {"funding_rate": ctx.get("funding")}

    async def place_order(
        self, symbol: str, side: str, amount: float, price: float
    ) -> Any:
        """Place a signed limit order via the Exchange API."""
        if self.exchange is None:
            raise ImportError("hyperliquid package is required")
        is_buy = side.lower() == "buy"
        res = await self.exchange.order(
            symbol,
            is_buy,
            amount,
            price,
            {"limit": {"tif": "Gtc"}},
        )
        try:
            return res["response"]["data"]["statuses"][0]["resting"]["oid"]
        except Exception:
            return None

    async def cancel_order(self, order_id: Any) -> None:
        """Cancel an existing order via the Exchange API."""
        if self.exchange is None:
            raise ImportError("hyperliquid package is required")
        await self.exchange.cancel(symbol=None, oid=order_id)  # type: ignore[arg-type]

    async def get_position(self, symbol: str) -> Dict[str, Any]:
        """Return current position info for the account."""
        state = await self.info.user_state(self.account_address)  # type: ignore[operator]
        for pos in state.get("assetPositions", []):
            if pos.get("position", {}).get("coin") == symbol:
                return pos
        return {}
