# Market Data MCP Server (stub)

Mock market-data source for the Analyst role. Every response is tagged
`"mock": true`. Replace with a real provider before paper trading is
meant to reflect real market conditions (backtest can run on real
historical data separately; this stub is about giving the Analyst
*something* to call today).

## Run locally

```
pip install -r requirements.txt
python server.py
```

## Wiring into Claude Code

Add to the Analyst role's MCP config (or the instance-wide `.mcp.json`
once created) as a stdio server pointing at this script. See
`docs/execution-plan.md` Section 4.

## Swapping in a real provider

Keep the same three tool names (`get_price`, `get_technicals`,
`get_news`) so nothing else in the repo needs to change — just point the
Analyst's MCP config at the new server process.
