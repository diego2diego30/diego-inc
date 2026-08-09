# Robinhood — read-only account visibility (setup instructions)

Robinhood offers an official "Agentic Trading" product
(https://robinhood.com/us/en/agentic-trading/): a dedicated account with a
budget cap, connected to a third-party AI agent via an official MCP
server, where "trades may be executed by an AI agent without your direct
input on each transaction."

**This repo only ever wires in the read/view tools from that server —
never the order-placement tool.** No role's `--allowedTools` should ever
include a trade/order tool name from this server, regardless of what
Robinhood's own product allows. See `hermes/execution_guard.py`: no
live-execution code path exists anywhere in this codebase, on any
institution, until Diego explicitly opens Gate 4 — and even then, that
guard governs a future *real* execution path this repo builds and audits
itself, not a third party's black-box agent loop.

## Setup (one-time, must be done by Diego — not automatable)

1. On Robinhood, create a dedicated agentic-trading account with its own
   budget cap (do **not** connect your primary account).
2. Complete their connection flow to get the MCP server URL.
3. Before wiring anything in, list the server's advertised tools (e.g.
   `claude mcp list-tools` against the URL, or check Robinhood's own MCP
   docs) and write down the exact tool names for balance/positions vs.
   order placement — Robinhood hasn't published a name in their overview
   page, so this has to be read off the live server.
4. Set the MCP URL in `deploy/.env` as `ROBINHOOD_MCP_URL`.

## Wiring in (once you have the URL + tool names)

Add to `trading/.mcp.json`, alongside `market-data` and `accounts`:

```json
"robinhood": {
  "type": "url",
  "url": "$ROBINHOOD_MCP_URL"
}
```

(Exact shape depends on whether it's a plain HTTP or SSE MCP transport —
check Robinhood's docs; adjust the `type` field to match.)

Then in `hermes/orchestrator.py` `ROLE_ALLOWED_TOOLS["analyst"]`, add
**only** the read/view tool names, e.g.:

```python
"mcp__robinhood__get_positions",
"mcp__robinhood__get_account_balance",
# NEVER add the order/trade-placement tool name here.
```

Update `trading/roles/analyst/CLAUDE.md` the same way the market-data and
accounts tools were documented, and double-check the final
`--allowedTools` list for the analyst role has no Robinhood tool whose
name suggests it places, cancels, or modifies an order.
