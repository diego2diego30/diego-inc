"""Stub market-data MCP server (execution-plan.md Section 4).

Returns clearly-labeled mock data over stdio via the MCP Python SDK. This
exists so the Analyst role has a real MCP endpoint to call and the full
chain is exercisable end-to-end in backtest/paper mode before Diego picks
a real market-data provider. Every response is tagged "mock": true so
nothing downstream can mistake this for real market data.

Swap-in path for a real provider: implement the same three tool names
(get_price, get_technicals, get_news) against the real API/SDK, remove the
"mock": true tag, and point roles/analyst's --allowedTools /
MCP server config at the new process instead of this one. No other file
in this repo should need to change.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("market-data-stub")


def _seeded_random(ticker: str) -> random.Random:
    # Deterministic per-ticker-per-day so repeated calls in one cycle are
    # self-consistent, without needing any real backing store.
    seed = f"{ticker}-{datetime.now(timezone.utc).date().isoformat()}"
    return random.Random(seed)


@mcp.tool()
def get_price(ticker: str) -> dict:
    """Mock last price + volume for a ticker. Real provider TBD -- see
    docs/execution-plan.md Section 4.
    """
    rnd = _seeded_random(ticker)
    price = round(rnd.uniform(10, 500), 2)
    return {
        "mock": True,
        "ticker": ticker,
        "price": price,
        "volume": rnd.randint(100_000, 50_000_000),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


@mcp.tool()
def get_technicals(ticker: str) -> dict:
    """Mock technical indicators for a ticker."""
    rnd = _seeded_random(ticker)
    return {
        "mock": True,
        "ticker": ticker,
        "sma_50": round(rnd.uniform(10, 500), 2),
        "sma_200": round(rnd.uniform(10, 500), 2),
        "rsi_14": round(rnd.uniform(0, 100), 1),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


@mcp.tool()
def get_news(ticker: str, limit: int = 5) -> dict:
    """Mock recent headlines for a ticker. Low-confidence by construction
    -- real news/sentiment wiring should preserve the Section 1 guidance
    that social/news signal is a weak input to the Analyst, not a trigger.
    """
    rnd = _seeded_random(ticker)
    headlines = [f"[mock] {ticker} headline #{i + 1}" for i in range(min(limit, 5))]
    return {"mock": True, "ticker": ticker, "headlines": headlines, "confidence": "low"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
