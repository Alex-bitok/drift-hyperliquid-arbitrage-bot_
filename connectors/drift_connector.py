import asyncio
import logging

logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
from typing import Any, Dict

try:  # pragma: no cover - optional heavy deps
    from solders.keypair import Keypair
    from solana.rpc.async_api import AsyncClient

    from driftpy.drift_client import DriftClient
    from driftpy.dlob.dlob_subscriber import DLOBSubscriber, MarketId
    from driftpy.dlob.client_types import DLOBClientConfig
    from driftpy.user_map.user_map import UserMap
    from driftpy.user_map.user_map_config import UserMapConfig, WebsocketConfig
    from driftpy.slot.slot_subscriber import SlotSubscriber
    from driftpy.types import MarketType, OrderType, OrderParams, PositionDirection
    from driftpy.constants.numeric_constants import BASE_PRECISION, PRICE_PRECISION
except Exception:  # pragma: no cover - modules may be missing during tests

    class _Missing:  # pylint: disable=too-few-public-methods
        pass

    Keypair = AsyncClient = DriftClient = DLOBSubscriber = MarketId = _Missing
    DLOBClientConfig = UserMap = UserMapConfig = WebsocketConfig = SlotSubscriber = _Missing
    MarketType = OrderType = OrderParams = PositionDirection = _Missing
    BASE_PRECISION = 10**9
    PRICE_PRECISION = 10**6

from .base import ConnectorBase


class DriftConnector(ConnectorBase):
    """Connector implementation using DriftPy SDK."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.connection = None
        self.wallet = None
        self.client = None
        self.user_map = None
        self.slot_subscriber = None
        self._dlob = None
        self.ws_error_reported = False

    async def async_init(self) -> None:
        logger = logging.getLogger(__name__)
        rpc_url = self.config.get("rpc_url")
        if not rpc_url:
            raise RuntimeError("'rpc_url' must be provided in config")

        ws_url = self.config.get("ws_url")
        if ws_url:
            try:
                from driftpy import types as drift_types

                drift_types.get_ws_url = lambda _url: ws_url
            except Exception:
                pass

        async def _connect(url: str):
            conn = AsyncClient(url)
            await asyncio.wait_for(conn.get_slot(), timeout=5)
            wallet = Keypair.from_base58_string(self.config["private_key"])
            client = DriftClient(
                conn,
                wallet,
                env="mainnet",
                active_sub_account_id=self.config.get("sub_account_id", 0),
            )
            return conn, wallet, client

        max_attempts = 5


        for attempt in range(1, max_attempts + 1):
            try:
                self.connection, self.wallet, self.client = await _connect(rpc_url)
                try:
                    await self.client.subscribe()

                    user_map_config = UserMapConfig(self.client, WebsocketConfig())
                    self.user_map = UserMap(user_map_config)
                    await self.user_map.subscribe()

                    self.slot_subscriber = SlotSubscriber(self.client)
                    await self.slot_subscriber.subscribe()

                    dlob_config = DLOBClientConfig(
                        self.client,
                        self.user_map,
                        self.slot_subscriber,
                        1000,
                    )
                    self._dlob = DLOBSubscriber(config=dlob_config)
                    await self._dlob.subscribe()
                except Exception as e_sub:
                    logger.error("client.subscribe() failed with error: %s", e_sub)
                    raise
                if self.ws_error_reported:
                    logger.info("Reconnected to Drift")
                    self.ws_error_reported = False
                logger.info(
                    "DriftConnector initialized and subscribed to %s", rpc_url
                )
                break
            except Exception as e:
                if not self.ws_error_reported:
                    logger.warning("Drift WebSocket disconnected")
                    self.ws_error_reported = True
                logger.warning(
                    "[DriftConnector] RPC connect error: %s (attempt %s/%s)",
                    e,
                    attempt,
                    max_attempts,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(2)
                else:
                    raise RuntimeError(
                        f"Unable to connect to RPC endpoint {rpc_url} after {max_attempts} attempts: {e}"
                    )

    def _market_id(self, symbol: str) -> MarketId:
        idx, mtype = self.client.get_market_index_and_type(symbol)
        return MarketId(index=idx, kind=mtype)

    async def fetch_book(self, symbol: str) -> Dict[str, Any]:
        """Return best bid/ask using the DLOB API."""
        try:
            if not self._dlob:
                dlob_url = self.config.get("dlob_url")
                self._dlob = DLOBSubscriber(url=dlob_url)
                await self._dlob.subscribe()

            ob = self._dlob.get_l2_orderbook_sync(market_name=symbol)
            best_bid = ob.bids[0] if ob.bids else None
            best_ask = ob.asks[0] if ob.asks else None
            return {
                "bids": (
                    [
                        {
                            "price": best_bid.price / PRICE_PRECISION,
                            "size": best_bid.size / BASE_PRECISION,
                        }
                    ]
                    if best_bid
                    else []
                ),
                "asks": (
                    [
                        {
                            "price": best_ask.price / PRICE_PRECISION,
                            "size": best_ask.size / BASE_PRECISION,
                        }
                    ]
                    if best_ask
                    else []
                ),
            }
        except Exception:  # pragma: no cover - fallback when DLOB fails
            idx, _ = self.client.get_market_index_and_type(symbol)
            market = self.client.get_perp_market_account(idx)
            amm = getattr(market, "amm", None)
            price = getattr(amm, "last_oracle_price", 0) / PRICE_PRECISION if amm else 0
            return {
                "bids": [{"price": price, "size": 0}],
                "asks": [{"price": price, "size": 0}],
            }

    async def fetch_funding(
        self, symbol: str
    ) -> Dict[str, Any]:  # pragma: no cover - deprecated
        """Return funding info via RPC fallback."""
        idx, _ = self.client.get_market_index_and_type(symbol)
        market = self.client.get_perp_market_account(idx)
        amm = getattr(market, "amm", None) if market else None
        return {
            "last_funding_rate": getattr(amm, "last_funding_rate", 0) if amm else 0,
            "last24h_avg_funding_rate": (
                getattr(amm, "last24h_avg_funding_rate", 0) if amm else 0
            ),
        }

    async def place_order(
        self, symbol: str, side: str, amount: float, price: float
    ) -> Any:
        idx, _ = self.client.get_market_index_and_type(symbol)
        direction = (
            PositionDirection.Long()
            if side.lower() == "buy"
            else PositionDirection.Short()
        )
        state = getattr(self.client, "get_state_account", lambda: None)()
        base_prec = (
            getattr(state, "base_precision", BASE_PRECISION)
            if state
            else BASE_PRECISION
        )
        price_prec = (
            getattr(state, "price_precision", PRICE_PRECISION)
            if state
            else PRICE_PRECISION
        )
        order = OrderParams(
            order_type=OrderType.MARKET,  # <-- driftpy==0.8.63, Enum 
            base_asset_amount=int(amount * base_prec),
            market_index=idx,
            direction=direction,
            market_type=MarketType.Perp(),
            price=int(price * price_prec),
        )
        return await self.client.place_perp_order(order)

    async def cancel_order(self, order_id: Any) -> None:
        await self.client.cancel_order(order_id)

    async def get_position(self, symbol: str) -> Dict[str, Any]:
        idx, _ = self.client.get_market_index_and_type(symbol)
        pos = self.client.get_perp_position(idx)
        return {
            "base_asset_amount": getattr(pos, "base_asset_amount", 0) if pos else 0,
            "quote_asset_amount": getattr(pos, "quote_asset_amount", 0) if pos else 0,
        }
