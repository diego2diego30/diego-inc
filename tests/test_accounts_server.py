"""Section 4 coverage: the read-only Plaid-backed accounts MCP server.

Loaded by file path via importlib -- mcp_servers/accounts/server.py is a
standalone script (invoked as `python3 mcp_servers/accounts/server.py`,
per trading/.mcp.json), not part of the hermes package. There is no
write/transfer path in this server to test the absence of by exercising
it -- Plaid's Balance and Investments products simply don't expose one.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp_servers" / "accounts" / "server.py"
_spec = importlib.util.spec_from_file_location("accounts_server", _SERVER_PATH)
accounts_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(accounts_server)


class TestMissingConfig:
    def test_raises_when_client_credentials_missing(self, monkeypatch):
        monkeypatch.delenv("PLAID_CLIENT_ID", raising=False)
        monkeypatch.delenv("PLAID_SECRET", raising=False)
        monkeypatch.setenv("PLAID_ACCESS_TOKEN_WF", "token-wf")
        with pytest.raises(accounts_server.MissingAccountsConfig):
            accounts_server.get_account_balance("wf")

    def test_raises_when_institution_token_missing(self, monkeypatch):
        monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
        monkeypatch.setenv("PLAID_SECRET", "secret")
        monkeypatch.delenv("PLAID_ACCESS_TOKEN_ROBINHOOD", raising=False)
        with pytest.raises(accounts_server.MissingAccountsConfig):
            accounts_server.get_account_balance("robinhood")

    def test_rejects_unknown_plaid_env(self, monkeypatch):
        monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
        monkeypatch.setenv("PLAID_SECRET", "secret")
        monkeypatch.setenv("PLAID_ACCESS_TOKEN_WF", "token-wf")
        monkeypatch.setenv("PLAID_ENV", "not-a-real-env")
        with pytest.raises(accounts_server.MissingAccountsConfig):
            accounts_server.get_account_balance("wf")


class TestGetAccountBalance:
    def test_shapes_balances_by_account(self, monkeypatch):
        monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
        monkeypatch.setenv("PLAID_SECRET", "secret")
        monkeypatch.setenv("PLAID_ACCESS_TOKEN_WF", "token-wf")

        fake_response = {
            "accounts": [
                {
                    "name": "Everyday Checking",
                    "type": "depository",
                    "subtype": "checking",
                    "balances": {"available": 1234.56, "current": 1250.00, "iso_currency_code": "USD"},
                }
            ]
        }
        monkeypatch.setattr(accounts_server, "_plaid_post", lambda path, token, extra=None: fake_response)

        result = accounts_server.get_account_balance("wf")
        assert result["institution"] == "wf"
        assert result["accounts"] == [
            {
                "name": "Everyday Checking",
                "type": "depository",
                "subtype": "checking",
                "available": 1234.56,
                "current": 1250.00,
                "currency": "USD",
            }
        ]


class TestGetInvestmentHoldings:
    def test_joins_holdings_to_security_metadata(self, monkeypatch):
        monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
        monkeypatch.setenv("PLAID_SECRET", "secret")
        monkeypatch.setenv("PLAID_ACCESS_TOKEN_FIDELITY", "token-fidelity")

        fake_response = {
            "securities": [{"security_id": "sec1", "ticker_symbol": "SPY", "name": "SPDR S&P 500 ETF"}],
            "holdings": [
                {"security_id": "sec1", "quantity": 10.0, "institution_value": 5500.0, "iso_currency_code": "USD"}
            ],
        }
        monkeypatch.setattr(accounts_server, "_plaid_post", lambda path, token, extra=None: fake_response)

        result = accounts_server.get_investment_holdings("fidelity")
        assert result["institution"] == "fidelity"
        assert result["holdings"] == [
            {
                "ticker": "SPY",
                "name": "SPDR S&P 500 ETF",
                "quantity": 10.0,
                "market_value": 5500.0,
                "currency": "USD",
            }
        ]

    def test_empty_for_pure_bank_account(self, monkeypatch):
        monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
        monkeypatch.setenv("PLAID_SECRET", "secret")
        monkeypatch.setenv("PLAID_ACCESS_TOKEN_WF", "token-wf")
        monkeypatch.setattr(
            accounts_server, "_plaid_post", lambda path, token, extra=None: {"securities": [], "holdings": []}
        )
        result = accounts_server.get_investment_holdings("wf")
        assert result["holdings"] == []
