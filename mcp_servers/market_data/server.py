"""Real market-data MCP server (execution-plan.md Section 4), backed by
Alpaca's Market Data API.

Replaces the earlier mock stub. Keeps the same three tool names
(get_price, get_technicals, get_news) the mock used, per its own
swap-in note, so nothing else in the repo (ROLE_ALLOWED_TOOLS,
trading/.mcp.json, the Analyst role's CLAUDE.md) needs to change beyond
what's already wired.

Requires ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY (a free Alpaca
account's market-data-only keys -- no brokerage/trading scope needed).
Fails loudly at request time if they're missing rather than silently
falling back to fabricated numbers, matching hermes/config.py's
MissingConfigError philosophy: a visibly missing data point is safer
than one that looks real but isn't.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("market-data")

DATA_BASE_URL = "https://data.alpaca.markets"


class MissingMarketDataConfig(RuntimeError):
    pass


def _alpaca_headers() -> dict:
    key_id = os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key_id or not secret:
        raise MissingMarketDataConfig(
            "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY are not set. See "
            "deploy/.env.example. Refusing to return fabricated market data."
        )
    return {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}


def _get(path: str, params: dict) -> dict:
    resp = requests.get(f"{DATA_BASE_URL}{path}", headers=_alpaca_headers(), params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
def get_price(ticker: str) -> dict:
    """Last trade price and most recent daily bar's volume for a ticker,
    from Alpaca's real-time market data feed (IEX/SIP depending on plan).
    """
    trade = _get(f"/v2/stocks/{ticker}/trades/latest", {})["trade"]
    bar = _get(f"/v2/stocks/{ticker}/bars/latest", {})["bar"]
    return {
        "mock": False,
        "ticker": ticker,
        "price": trade["p"],
        "volume": bar["v"],
        "as_of": trade["t"],
    }


def _sma(closes: list, window: int) -> float | None:
    if len(closes) < window:
        return None
    return round(sum(closes[-window:]) / window, 2)


def _rsi_14(closes: list) -> float | None:
    """Standard Wilder RSI over the last 14 periods. Returns None (rather
    than a fabricated midpoint) if there isn't enough history yet.
    """
    period = 14
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


@mcp.tool()
def get_technicals(ticker: str) -> dict:
    """SMA-50, SMA-200, and RSI-14 computed from Alpaca daily bars. Fields
    are null (not a guessed value) when there isn't yet 200+ days of
    history for the ticker -- e.g. a recent IPO.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=400)  # buffer past 200 trading days for weekends/holidays
    data = _get(
        f"/v2/stocks/{ticker}/bars",
        {
            "timeframe": "1Day",
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "limit": 10000,
            "adjustment": "split",
        },
    )
    closes = [bar["c"] for bar in data.get("bars", [])]
    return {
        "mock": False,
        "ticker": ticker,
        "sma_50": _sma(closes, 50),
        "sma_200": _sma(closes, 200),
        "rsi_14": _rsi_14(closes),
        "as_of": closes and data["bars"][-1]["t"] or None,
    }


@mcp.tool()
def get_news(ticker: str, limit: int = 5) -> dict:
    """Recent headlines for a ticker via Alpaca's news feed. Always
    labeled low-confidence -- per trading/roles/analyst/CLAUDE.md and
    execution-plan.md Section 1, news/sentiment is a weak, lagging input
    that should never be the Analyst's headline finding.
    """
    data = _get("/v1beta1/news", {"symbols": ticker, "limit": min(limit, 5)})
    headlines = [item["headline"] for item in data.get("news", [])]
    return {"mock": False, "ticker": ticker, "headlines": headlines, "confidence": "low"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
