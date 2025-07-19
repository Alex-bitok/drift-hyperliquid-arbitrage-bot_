import asyncio
import pytest
import logging
from connectors.base import ConnectorBase
from execution.engine import ExecutionEngine


class DummyExecConnector(ConnectorBase):
    def __init__(self, fill_result):
        super().__init__({})
        self.fill_result = fill_result
        self.cancelled = []
        self.order_counter = 0
        self.position = {"base_asset_amount": 0}

    async def fetch_book(self, symbol: str):
        return {"bids": [], "asks": []}

    async def fetch_funding(self, symbol: str):
        return {}


    async def place_order(self, symbol, side, amount, price):
        self.order_counter += 1
        return self.order_counter

    async def cancel_order(self, order_id):
        self.cancelled.append(order_id)

    async def async_init(self):
        return None

    async def get_position(self, symbol):
        return self.position


@pytest.mark.asyncio
async def test_execute_pair_trade_partial_fill(monkeypatch):
    conn_a = DummyExecConnector(True)
    conn_b = DummyExecConnector(False)
    engine = ExecutionEngine(conn_a, conn_b, {})

    call_count = {"n": 0}

    async def fake_wait_fill(*args, **kwargs):
        call_count["n"] += 1
        return conn_a.fill_result if call_count["n"] == 1 else conn_b.fill_result

    monkeypatch.setattr(engine, "_wait_fill", fake_wait_fill)

    success = await engine.execute_pair_trade("A", "B", "buy", "sell", 1, 10, 11)
    assert not success
    assert engine.safe_mode_triggered
    assert conn_a.cancelled and conn_b.cancelled


@pytest.mark.asyncio
async def test_slippage_alert(monkeypatch, caplog):
    conn_a = DummyExecConnector(True)
    conn_b = DummyExecConnector(True)
    engine = ExecutionEngine(conn_a, conn_b, {"max_slippage_bps": 10})

    async def fake_wait_fill(*a, **k):
        return True

    monkeypatch.setattr(engine, "_wait_fill", fake_wait_fill)
    monkeypatch.setattr(engine, "_calc_fill_price", lambda *a, **k: 12.0)
    monkeypatch.setattr("execution.engine.log_event", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING):
        success = await engine.execute_pair_trade("A", "B", "buy", "sell", 1, 10, 10)

    assert success
    assert any("ALERT: Slippage exceeded" in r.message for r in caplog.records)
