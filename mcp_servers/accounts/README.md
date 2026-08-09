# Accounts MCP Server (read-only)

Gives the Analyst role visibility into real account balances (Wells Fargo)
and brokerage holdings (Fidelity), via Plaid's Balance and Investments
products. **Read-only by construction** -- neither Plaid product this
server calls has a write/transfer capability, and none should ever be
added here. See `hermes/execution_guard.py` for why: no live-execution
code path exists anywhere in this repo until Diego explicitly opens
Gate 4.

## Setup (one-time, must be done by Diego -- not automatable)

1. Sign up for a Plaid developer account at https://dashboard.plaid.com.
2. Get `PLAID_CLIENT_ID` / `PLAID_SECRET` from the dashboard, and pick a
   `PLAID_ENV` (`sandbox` to test, `development` or `production` for
   real accounts).
3. Run the Plaid Link flow once per institution to link Wells Fargo and
   Fidelity -- this requires your real bank/brokerage login and can't be
   done by an agent. Plaid's own quickstart
   (https://plaid.com/docs/quickstart/) has a minimal Link-flow web app
   you run locally just to generate the access token.
4. Each Link flow gives you one `access_token`. Set it as
   `PLAID_ACCESS_TOKEN_WF` and `PLAID_ACCESS_TOKEN_FIDELITY` in
   `deploy/.env`.

## Run locally

```
pip install -r requirements.txt
python server.py
```

## Wiring into Claude Code

Registered in `trading/.mcp.json` as a stdio server. Only the Analyst
role has it in `--allowedTools` (see `hermes/orchestrator.py`
`ROLE_ALLOWED_TOOLS`).

## Tools

- `get_account_balance(institution)` -- balances for every account under
  `institution` (`"wf"` or `"fidelity"`)
- `get_investment_holdings(institution)` -- current positions for a
  brokerage institution (`"fidelity"`); empty for pure bank accounts
