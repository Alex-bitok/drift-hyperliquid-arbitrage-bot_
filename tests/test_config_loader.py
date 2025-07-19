import os
import pytest
from pydantic import ValidationError
from config import ConfigLoader

def test_env_fallback(monkeypatch, tmp_path):
    cfg = """
market: TEST
amount: 1
strategies: {}
drift:
  rpc_url: http://foo
  market: D
hyperliquid:
  account_address: "0x1"
  market: H
"""
    p = tmp_path / "c.yml"
    p.write_text(cfg)

    monkeypatch.setenv("DRIFT_PRIVATE_KEY", "pkey")
    monkeypatch.setenv("HYPERLIQUID_API_KEY", "key")
    monkeypatch.setenv("HYPERLIQUID_API_SECRET", "sec")

    loader = ConfigLoader(str(p))
    model = loader.load()
    assert model.drift.private_key == "pkey"
    assert model.hyperliquid.api_key == "key"
    assert model.hyperliquid.api_secret == "sec"


def test_empty_file(monkeypatch, tmp_path):
    """Loader should handle an empty config file gracefully."""
    p = tmp_path / "c.yml"
    p.write_text("")

    # ensure no environment variables accidentally satisfy required fields
    monkeypatch.delenv("DRIFT_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("HYPERLIQUID_API_KEY", raising=False)
    monkeypatch.delenv("HYPERLIQUID_API_SECRET", raising=False)

    loader = ConfigLoader(str(p))
    with pytest.raises(ValidationError):
        loader.load()
