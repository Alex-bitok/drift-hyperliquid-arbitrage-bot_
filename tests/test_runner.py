from unittest.mock import patch

from strategies.runner import MultiStrategyRunner
from strategies.basis import BasisStrategy
from strategies.funding import FundingStrategy
from connectors.base import ConnectorBase


class DummyConnector(ConnectorBase):
    def __init__(self, *a, **kw):
        super().__init__({})
        self.book = {"bids": [{"price": 0}], "asks": [{"price": 0}]}
        self.funding = {"funding_rate": 0}

    async def fetch_book(self, symbol: str):
        return self.book

    async def fetch_funding(self, symbol: str):
        return self.funding

    async def place_order(self, symbol, side, amount, price):
        return 1

    async def cancel_order(self, order_id):
        pass

    async def async_init(self):
        return None

    async def get_position(self, symbol):
        return {"base_asset_amount": 0}


class DummyEngine:
    def __init__(self, *a, **kw):
        pass

    async def execute_pair_trade(self, *a, **kw):
        return True


def test_runner_instantiates_strategies():
    config = {
        "market": "TEST",
        "amount": 1.0,
        "drift": {"market": "D"},
        "hyperliquid": {"market": "H"},
        "strategies": {
            "basis": {"enabled": True},
            "funding": {"enabled": True},
        },
    }

    with patch("strategies.base.ExecutionEngine", lambda a, b, c: DummyEngine()):
        drift = DummyConnector()
        hyper = DummyConnector()
        runner = MultiStrategyRunner(config, drift=drift, hyper=hyper)

    types = {type(s) for s in runner.strategies}
    assert BasisStrategy in types
    assert FundingStrategy in types
