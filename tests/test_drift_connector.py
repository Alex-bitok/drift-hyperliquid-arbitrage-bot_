import pytest

from connectors.drift_connector import DriftConnector


class DummyAsyncClient:
    def __init__(self, url, ok=True):
        self.url = url
        self.ok = ok
        DummyAsyncClient.created.append(url)

    async def get_slot(self):
        if self.ok:
            return 1
        raise Exception("boom")


DummyAsyncClient.created = []


import asyncio


@pytest.mark.asyncio
async def test_drift_connector_fails_single_rpc(monkeypatch):
    monkeypatch.setattr(
        "connectors.drift_connector.AsyncClient",
        lambda url: DummyAsyncClient(url, ok=False),
    )

    # patch DriftClient so it is not instantiated after failure
    class DummyDC:
        pass

    monkeypatch.setattr(
        "connectors.drift_connector.DriftClient", lambda *a, **k: DummyDC()
    )

    class DummyKP:
        @staticmethod
        def from_base58_string(v):
            return "kp"

    monkeypatch.setattr("connectors.drift_connector.Keypair", DummyKP)

    conn = DriftConnector({"rpc_url": "http://one", "private_key": "key"})
    with pytest.raises(RuntimeError):
        await conn.async_init()

    assert DummyAsyncClient.created == ["http://one"] * 5


@pytest.mark.asyncio
async def test_drift_fetch_methods(monkeypatch):
    monkeypatch.setattr(
        "connectors.drift_connector.AsyncClient",
        lambda url: DummyAsyncClient(url, ok=True),
    )

    # patch additional driftpy helpers used for DLOBSubscriber initialization
    class DummyUserMap:
        async def subscribe(self):
            return None

    class DummySlotSub:
        async def subscribe(self):
            return None

    class DummyDLOB:
        async def subscribe(self):
            return None

        def get_l2_orderbook_sync(self, *a, **k):
            return DummyOB()

    monkeypatch.setattr("connectors.drift_connector.UserMap", lambda *a, **k: DummyUserMap())
    monkeypatch.setattr(
        "connectors.drift_connector.UserMapConfig",
        lambda *a, **k: object(),
    )
    monkeypatch.setattr("connectors.drift_connector.WebsocketConfig", lambda *a, **k: object())
    monkeypatch.setattr("connectors.drift_connector.SlotSubscriber", lambda *a, **k: DummySlotSub())
    monkeypatch.setattr(
        "connectors.drift_connector.DLOBClientConfig",
        lambda *a, **k: object(),
    )

    class DummyDC:
        connection = object()

        def get_market_index_and_type(self, symbol):
            return 0, None

        def get_perp_market_account(self, idx):
            class AMM:
                last_funding_rate = 0.02
                last24h_avg_funding_rate = 0.03
                last_oracle_price = 1_000_000

            class Market:
                amm = AMM()

            return Market()

        async def subscribe(self):
            return None

    monkeypatch.setattr(
        "connectors.drift_connector.DriftClient", lambda *a, **k: DummyDC()
    )

    class DummyKP:
        @staticmethod
        def from_base58_string(v):
            return "kp"

    monkeypatch.setattr("connectors.drift_connector.Keypair", DummyKP)

    class DummyLevel:
        def __init__(self, price, size):
            self.price = price
            self.size = size

    class DummyOB:
        def __init__(self):
            self.bids = [DummyLevel(10_000_000, 1_000_000_000)]
            self.asks = [DummyLevel(11_000_000, 1_000_000_000)]

    # DummyDLOB is defined above as part of subscription patches

    class DummyMarketId:
        def __init__(self, index, kind):
            self.index = index
            self.kind = kind

    monkeypatch.setattr(
        "connectors.drift_connector.DLOBSubscriber", lambda *a, **k: DummyDLOB()
    )
    monkeypatch.setattr("connectors.drift_connector.MarketId", DummyMarketId)
    monkeypatch.setattr("connectors.drift_connector.BASE_PRECISION", 1_000_000_000)
    monkeypatch.setattr("connectors.drift_connector.PRICE_PRECISION", 1_000_000)

    conn = DriftConnector({"rpc_url": "http://one", "private_key": "key"})
    await conn.async_init()
    book = await conn.fetch_book("SOL-PERP")
    funding = await conn.fetch_funding("SOL-PERP")

    assert book["bids"][0]["price"] == 10.0
    assert book["asks"][0]["price"] == 11.0
    assert funding["last_funding_rate"] == 0.02


@pytest.mark.asyncio
async def test_drift_ws_url_override(monkeypatch):
    drift_types = pytest.importorskip("driftpy.types")

    monkeypatch.setattr(
        "connectors.drift_connector.AsyncClient",
        lambda url: DummyAsyncClient(url, ok=True),
    )

    # patch helper classes so initialization doesn't touch network
    class DummyUserMap:
        async def subscribe(self):
            return None

    class DummySlotSub:
        async def subscribe(self):
            return None

    class DummyDLOB:
        async def subscribe(self):
            return None

        def get_l2_orderbook_sync(self, *a, **k):
            class Level:
                price = 0
                size = 0
            return type("OB", (), {"bids": [Level()], "asks": [Level()]})()

    monkeypatch.setattr("connectors.drift_connector.UserMap", lambda *a, **k: DummyUserMap())
    monkeypatch.setattr("connectors.drift_connector.UserMapConfig", lambda *a, **k: object())
    monkeypatch.setattr("connectors.drift_connector.WebsocketConfig", lambda *a, **k: object())
    monkeypatch.setattr("connectors.drift_connector.SlotSubscriber", lambda *a, **k: DummySlotSub())
    monkeypatch.setattr("connectors.drift_connector.DLOBClientConfig", lambda *a, **k: object())
    monkeypatch.setattr("connectors.drift_connector.DLOBSubscriber", lambda *a, **k: DummyDLOB())

    class DummyDC:
        connection = object()

        async def subscribe(self):
            return None

    monkeypatch.setattr(
        "connectors.drift_connector.DriftClient", lambda *a, **k: DummyDC()
    )

    class DummyKP:
        @staticmethod
        def from_base58_string(v):
            return "kp"

    monkeypatch.setattr("connectors.drift_connector.Keypair", DummyKP)

    original = drift_types.get_ws_url
    try:
        conn = DriftConnector(
            {"rpc_url": "http://one", "private_key": "key", "ws_url": "wss://foo"}
        )
        await conn.async_init()
        assert drift_types.get_ws_url("anything") == "wss://foo"
    finally:
        drift_types.get_ws_url = original
