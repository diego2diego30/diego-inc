"""Read-only bank/brokerage account MCP server (execution-plan.md
Section 4: "the trading account API -- read-only scopes wherever
possible").

Backed by Plaid's Balance and Investments products. There is no write
path here and none should ever be added -- Plaid's Balance/Investments
products are inherently read-only (Plaid also offers a Transfer product
for moving money; this server deliberately never calls it, and no
institution's real order-placement or fund-transfer API should be wired
in here or anywhere else in this repo -- see hermes/execution_guard.py).

One access token per linked institution, set as
PLAID_ACCESS_TOKEN_<INSTITUTION>. Access tokens come from a one-time
Plaid Link flow that only Diego can complete (it requires his real bank
login) -- this server only ever consumes an already-issued token, never
performs the Link flow itself.
"""
from __future__ import annotations

import os

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("accounts")

PLAID_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


class MissingAccountsConfig(RuntimeError):
    pass


def _plaid_base_url() -> str:
    env = os.environ.get("PLAID_ENV", "development")
    if env not in PLAID_HOSTS:
        raise MissingAccountsConfig(
            f"PLAID_ENV={env!r} is not one of {list(PLAID_HOSTS)}. See deploy/.env.example."
        )
    return PLAID_HOSTS[env]


def _access_token(institution: str) -> str:
    env_name = f"PLAID_ACCESS_TOKEN_{institution.upper()}"
    token = os.environ.get(env_name)
    if not token:
        raise MissingAccountsConfig(
            f"{env_name} is not set. See deploy/.env.example -- an access "
            f"token for {institution!r} must be generated once via Plaid "
            f"Link (requires Diego's own bank login; cannot be automated "
            f"from here). Refusing to fabricate a balance."
        )
    return token


def _plaid_post(path: str, access_token: str, extra: dict | None = None) -> dict:
    client_id = os.environ.get("PLAID_CLIENT_ID")
    secret = os.environ.get("PLAID_SECRET")
    if not client_id or not secret:
        raise MissingAccountsConfig(
            "PLAID_CLIENT_ID / PLAID_SECRET are not set. See deploy/.env.example."
        )
    body = {"client_id": client_id, "secret": secret, "access_token": access_token}
    body.update(extra or {})
    resp = requests.post(f"{_plaid_base_url()}{path}", json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
def get_account_balance(institution: str) -> dict:
    """Current balance for every account under a linked institution
    (e.g. "wf", "fidelity"). Read-only -- Plaid's Balance product has no
    write capability. institution must have a matching
    PLAID_ACCESS_TOKEN_<INSTITUTION> env var.
    """
    data = _plaid_post("/accounts/balance/get", _access_token(institution))
    accounts = [
        {
            "name": a["name"],
            "type": a["type"],
            "subtype": a["subtype"],
            "available": a["balances"]["available"],
            "current": a["balances"]["current"],
            "currency": a["balances"]["iso_currency_code"],
        }
        for a in data.get("accounts", [])
    ]
    return {"institution": institution, "accounts": accounts}


@mcp.tool()
def get_investment_holdings(institution: str) -> dict:
    """Current security holdings (ticker, quantity, market value) for a
    linked brokerage institution (e.g. "fidelity"). Read-only -- Plaid's
    Investments product has no order-placement capability. Only
    meaningful for accounts of type "investment"; a pure bank account
    (e.g. "wf") will return an empty holdings list.
    """
    data = _plaid_post("/investments/holdings/get", _access_token(institution))
    securities_by_id = {s["security_id"]: s for s in data.get("securities", [])}
    holdings = []
    for h in data.get("holdings", []):
        sec = securities_by_id.get(h["security_id"], {})
        holdings.append({
            "ticker": sec.get("ticker_symbol"),
            "name": sec.get("name"),
            "quantity": h["quantity"],
            "market_value": h["institution_value"],
            "currency": h["iso_currency_code"],
        })
    return {"institution": institution, "holdings": holdings}


if __name__ == "__main__":
    mcp.run(transport="stdio")
