import pytest

from connectors.hyperliquid_connector import HyperliquidConnector


class DummyInfo:
    def meta_and_asset_ctxs(self):
        return {"universe": [{"name": "SOL"}]}, [{"impactPxs": ["1", "2"], "funding": 0.03}]

    async def user_state(self, addr):
        return {"assetPositions": [], "marginSummary": {"accountValue": 10}}


class DummyExchange:
    async def order(self, *a, **k):
        return {"response": {"data": {"statuses": [{"resting": {"oid": 1}}]}}}

    async def cancel(self, *a, **k):
        return {}


@pytest.mark.asyncio
async def test_hyperliquid_fetch_methods(monkeypatch):
    monkeypatch.setattr('connectors.hyperliquid_connector.Info', lambda *a, **k: DummyInfo())
    monkeypatch.setattr('connectors.hyperliquid_connector.Exchange', lambda *a, **k: DummyExchange())
    class DummyAccount:
        @staticmethod
        def from_key(key):
            return "acc"

    monkeypatch.setattr('connectors.hyperliquid_connector.Account', DummyAccount)
    conn = HyperliquidConnector({'api_key': 'k', 'account_address': '0x1', 'api_url': 'http://api'})
    await conn.async_init()
    book = await conn.fetch_book('SOL')
    funding = await conn.fetch_funding('SOL')
    assert book['bids'][0]['price'] == 1.0
    assert funding['funding_rate'] == 0.03

