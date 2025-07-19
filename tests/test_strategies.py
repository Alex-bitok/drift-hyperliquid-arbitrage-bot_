import threading
from unittest.mock import AsyncMock, patch

import asyncio
import pytest

from connectors.base import ConnectorBase
from strategies.basis import BasisStrategy
from strategies.funding import FundingStrategy


class DummyConnector(ConnectorBase):
    def __init__(self, book=None, funding=None):
        super().__init__({})
        self.book = book or {"bids": [{"price": 0}], "asks": [{"price": 0}]}
        self.funding = funding or {"funding_rate": 0}

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


def make_strategy(cls, drift_book, hyper_book, drift_funding=None, hyper_funding=None, **cfg):
    drift = DummyConnector(drift_book, drift_funding)
    hyper = DummyConnector(hyper_book, hyper_funding)
    config = {
        "market": "TEST",
        "amount": 1.0,
        "max_slippage_bps": 0,
        "min_profit_usd": 0,
        "poll_interval_sec": 0.01,
        "drift": {"market": "D"},
        "hyperliquid": {"market": "H"},
    }
    config.update(cfg)
    with patch("strategies.base.ExecutionEngine", lambda a, b, c: DummyEngine()):
        strat = cls(config, drift=drift, hyper=hyper)
    return strat


@pytest.mark.asyncio
async def test_basis_long_drift():
    drift_book = {"bids": [{"price": 99}], "asks": [{"price": 101}]}
    hyper_book = {"bids": [{"price": 102}], "asks": [{"price": 104}]}
    strat = make_strategy(BasisStrategy, drift_book, hyper_book, min_profit_usd=0.5)
    opp = await strat.find_opportunity()
    assert opp["long_exchange"] == "drift"
    assert opp["short_exchange"] == "hyperliquid"


@pytest.mark.asyncio
async def test_basis_long_hyper():
    drift_book = {"bids": [{"price": 102}], "asks": [{"price": 104}]}
    hyper_book = {"bids": [{"price": 103}], "asks": [{"price": 101}]}
    strat = make_strategy(BasisStrategy, drift_book, hyper_book, min_profit_usd=0.5)
    opp = await strat.find_opportunity()
    assert opp["long_exchange"] == "hyperliquid"
    assert opp["short_exchange"] == "drift"


@pytest.mark.asyncio
async def test_basis_no_opportunity():
    drift_book = {"bids": [{"price": 99}], "asks": [{"price": 101}]}
    hyper_book = {"bids": [{"price": 100}], "asks": [{"price": 102}]}
    strat = make_strategy(BasisStrategy, drift_book, hyper_book, min_profit_usd=2)
    assert await strat.find_opportunity() is None


@pytest.mark.asyncio
async def test_basis_empty_orderbook_logs():
    drift_book = {"bids": [], "asks": []}
    hyper_book = {"bids": [{"price": 100}], "asks": [{"price": 101}]}
    strat = make_strategy(BasisStrategy, drift_book, hyper_book)
    hyper_book_mock = AsyncMock(return_value=hyper_book)
    strat.hyper.fetch_book = hyper_book_mock

    opp = await strat.find_opportunity()

    assert opp is None
    hyper_book_mock.assert_not_called()


@pytest.mark.asyncio
async def test_funding_positive_spread():
    drift_book = {"bids": [{"price": 100}], "asks": [{"price": 102}]}
    hyper_book = {"bids": [{"price": 100}], "asks": [{"price": 102}]}
    drift_funding = {"last_funding_rate": 0.01}
    hyper_funding = {"funding_rate": -0.01}
    strat = make_strategy(FundingStrategy, drift_book, hyper_book, drift_funding, hyper_funding, min_profit_usd=1)
    opp = await strat.find_opportunity()
    assert opp["long_exchange"] == "hyperliquid"
    assert opp["short_exchange"] == "drift"


@pytest.mark.asyncio
async def test_funding_negative_spread():
    drift_book = {"bids": [{"price": 100}], "asks": [{"price": 102}]}
    hyper_book = {"bids": [{"price": 100}], "asks": [{"price": 102}]}
    drift_funding = {"last_funding_rate": -0.01}
    hyper_funding = {"funding_rate": 0.01}
    strat = make_strategy(FundingStrategy, drift_book, hyper_book, drift_funding, hyper_funding, min_profit_usd=1)
    opp = await strat.find_opportunity()
    assert opp["long_exchange"] == "drift"
    assert opp["short_exchange"] == "hyperliquid"


@pytest.mark.asyncio
async def test_strategy_runs_until_stopped(monkeypatch):
    drift_book = {"bids": [{"price": 100}], "asks": [{"price": 101}]}
    hyper_book = {"bids": [{"price": 101}], "asks": [{"price": 102}]}
    strat = make_strategy(BasisStrategy, drift_book, hyper_book)

    async def _fake_find(self):
        return {
            "long_exchange": "drift",
            "short_exchange": "hyperliquid",
            "long_price": 1,
            "short_price": 2,
            "profit": 1.0,
        }

    monkeypatch.setattr(BasisStrategy, "find_opportunity", _fake_find)

    processed = []

    def fake_sim(self, opp):
        processed.append(opp)
        if len(processed) >= 2:
            self.stop()

    monkeypatch.setattr(BasisStrategy, "simulate", fake_sim)

    t = threading.Thread(target=lambda: asyncio.run(strat.run(live=False)))
    t.start()
    t.join(timeout=1)
    assert not t.is_alive()
    assert len(processed) == 2


class CaptureEngine:
    def __init__(self, *a, **kw):
        self.calls = []

    async def execute_pair_trade(self, *args, **kwargs):
        self.calls.append(args)
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "long_exchange,side_a,side_b",
    [
        ("drift", "sell", "buy"),
        ("hyperliquid", "buy", "sell"),
    ],
)
async def test_execute_passes_correct_sides(long_exchange, side_a, side_b):
    drift = DummyConnector()
    hyper = DummyConnector()
    engine = CaptureEngine()

    config = {
        "market": "TEST",
        "amount": 1.0,
        "drift": {"market": "D"},
        "hyperliquid": {"market": "H"},
    }

    with patch("strategies.base.ExecutionEngine", lambda a, b, c: engine):
        strat = BasisStrategy(config, drift=drift, hyper=hyper)

    opportunity = {
        "long_exchange": long_exchange,
        "short_exchange": "hyperliquid" if long_exchange == "drift" else "drift",
        "long_price": 10,
        "short_price": 9,
    }

    await strat.execute(opportunity)

    assert engine.calls
    call = engine.calls[0]
    exp_price_a = opportunity["short_price"] if long_exchange == "drift" else opportunity["long_price"]
    exp_price_b = opportunity["long_price"] if long_exchange == "drift" else opportunity["short_price"]
    assert call == ("H", "D", side_a, side_b, 1.0, exp_price_a, exp_price_b)
