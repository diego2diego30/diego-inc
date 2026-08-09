"""Section 4 coverage: the real (Alpaca-backed) market-data MCP server.

Loaded by file path via importlib rather than a normal package import --
mcp_servers/market_data/server.py is a standalone script (invoked as
`python3 mcp_servers/market_data/server.py`, per trading/.mcp.json), not
part of the hermes package.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp_servers" / "market_data" / "server.py"
_spec = importlib.util.spec_from_file_location("market_data_server", _SERVER_PATH)
market_data_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(market_data_server)


class TestMissingConfig:
    def test_get_price_raises_without_credentials(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
        monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
        with pytest.raises(market_data_server.MissingMarketDataConfig):
            market_data_server.get_price("AAPL")


class TestGetPrice:
    def test_reads_price_and_volume(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
        monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")

        def fake_get(path, params):
            if "trades/latest" in path:
                return {"trade": {"p": 123.45, "t": "2026-08-09T14:00:00Z"}}
            return {"bar": {"v": 1_000_000}}

        monkeypatch.setattr(market_data_server, "_get", fake_get)
        result = market_data_server.get_price("AAPL")
        assert result == {
            "mock": False,
            "ticker": "AAPL",
            "price": 123.45,
            "volume": 1_000_000,
            "as_of": "2026-08-09T14:00:00Z",
        }


class TestTechnicals:
    def test_sma_none_when_insufficient_history(self):
        assert market_data_server._sma([1.0, 2.0, 3.0], 50) is None

    def test_sma_averages_last_n_closes(self):
        closes = [10.0, 20.0, 30.0, 40.0]
        assert market_data_server._sma(closes, 2) == 35.0

    def test_rsi_none_when_insufficient_history(self):
        assert market_data_server._rsi_14([1.0] * 10) is None

    def test_rsi_100_when_no_losses(self):
        closes = [100.0 + i for i in range(15)]  # strictly increasing
        assert market_data_server._rsi_14(closes) == 100.0

    def test_rsi_between_0_and_100_for_mixed_moves(self):
        closes = [100, 102, 101, 105, 103, 108, 107, 110, 109, 112, 111, 115, 114, 118, 117]
        rsi = market_data_server._rsi_14([float(c) for c in closes])
        assert 0.0 <= rsi <= 100.0


class TestGetNews:
    def test_always_tagged_low_confidence(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
        monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
        monkeypatch.setattr(
            market_data_server,
            "_get",
            lambda path, params: {"news": [{"headline": "Something happened"}]},
        )
        result = market_data_server.get_news("AAPL")
        assert result["confidence"] == "low"
        assert result["headlines"] == ["Something happened"]
        assert result["mock"] is False
