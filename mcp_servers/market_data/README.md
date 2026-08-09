# Market Data MCP Server

Real market-data source for the Analyst role, backed by Alpaca's Market
Data API. Every response is tagged `"mock": false`. (The earlier stub
tagged every response `"mock": true` for the same reason -- so nothing
downstream could ever mistake fabricated numbers for real ones.)

## Setup

1. Create a free Alpaca account and generate a market-data API key pair
   (no brokerage/trading scope needed -- this server only ever reads).
2. Set `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` in `deploy/.env`.

## Run locally

```
pip install -r requirements.txt
python server.py
```

## Wiring into Claude Code

Registered in `trading/.mcp.json` as a stdio server. Only the Analyst
role has it in `--allowedTools` (see `hermes/orchestrator.py`
`ROLE_ALLOWED_TOOLS`) -- no other role reads market data directly.

## Tools

- `get_price(ticker)` -- last trade price, most recent daily volume
- `get_technicals(ticker)` -- SMA-50, SMA-200, RSI-14 from daily bars
  (fields are `null`, not guessed, when there isn't enough history yet)
- `get_news(ticker, limit=5)` -- recent headlines, always tagged
  `"confidence": "low"` per `docs/execution-plan.md` Section 1
