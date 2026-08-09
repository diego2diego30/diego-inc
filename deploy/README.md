# Deploying the trading instance to the VPS

This repo produces code and deploy artifacts only — nothing in this
session pushed anything to your Cloudflare VPS (no SSH access from this
environment). Run the steps below yourself, or from a local Claude Code
CLI session that does have SSH access to the VPS.

## 1. Checkout on the VPS

```
cd /root
git clone <this repo's URL> diego-inc
cd diego-inc
```

The `trading/` directory inside this checkout *is*
`/root/diego-inc/trading/` from execution-plan.md Section A — no separate
copy step needed as long as you check the repo out at
`/root/diego-inc`.

## 2. Fill in real configuration

```
cp deploy/.env.example deploy/.env
$EDITOR deploy/.env
```

Required before anything runs at all: `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY` (or headless auth via
`claude setup-token`). Required before any gate past Backtest: real,
reviewed values for the four Section 2 hard limits.

`deploy/.env` is gitignored — it will never get committed or pushed.

## 2a. Wire up real market data and read-only account visibility (optional, recommended)

The Analyst role can now see real prices/technicals/news and real account
balances instead of the old mock stub — but each source needs a one-time
setup step **only you can do** (bank/brokerage login, or a paid account
signup). None of this is automatable from a Claude Code session; do these
yourself, then drop the resulting keys/tokens into `deploy/.env`.

1. **Market data (Alpaca)** — quickest, self-serve. Sign up at
   https://alpaca.markets, generate a market-data API key pair (no
   brokerage scope needed), set `ALPACA_API_KEY_ID` /
   `ALPACA_API_SECRET_KEY`. See `mcp_servers/market_data/README.md`.

2. **Wells Fargo + Fidelity balances (Plaid)** — sign up for a Plaid
   developer account at https://dashboard.plaid.com, get
   `PLAID_CLIENT_ID` / `PLAID_SECRET`, then run Plaid's Link flow once
   per institution (their quickstart has a minimal local web app for
   this — https://plaid.com/docs/quickstart/). This requires your real
   WF/Fidelity login; nobody else can do it for you. Each Link run gives
   you one access token — set `PLAID_ACCESS_TOKEN_WF` and
   `PLAID_ACCESS_TOKEN_FIDELITY`. See `mcp_servers/accounts/README.md`.
   This is read-only by construction — there is no write/transfer path
   in this server, and none should ever be added.

3. **Robinhood balances (official agentic-trading MCP)** — create a
   *dedicated* agentic account on Robinhood with its own budget cap
   (https://robinhood.com/us/en/agentic-trading/), not your primary
   account. Get the MCP URL from their connection flow, set it as
   `ROBINHOOD_MCP_URL`. **Before wiring it into `trading/.mcp.json`**,
   read `mcp_servers/robinhood/README.md` in full — the order-placement
   tool that server also exposes must never be added to any role's
   `--allowedTools`, regardless of what Robinhood's own product allows.

None of these are required to run the chain — without them the Analyst
just has less context. Add them incrementally as you complete each setup
step.

## 3. Build and start the Telegram daemon

```
docker compose build
sudo cp deploy/systemd/diego-trading-hermes.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now diego-trading-hermes
systemctl status diego-trading-hermes
```

You should get a Telegram message once the bot comes up (add a startup
ping in `hermes/telegram_bridge.py` if you want one — not included by
default to avoid noise on every restart).

## 4. Install the cron schedule

```
crontab -e
# paste the line(s) from deploy/cron/trading-crontab, adjusting the path
```

## 5. Run one cycle by hand to verify

```
docker compose run --rm hermes-trading-chain --universe "SPY,QQQ"
```

Check `trading/logs/` for the new `.jsonl` run log and confirm Telegram
received the summary.

## 6. Run the test suite before trusting any of this

```
pip install -r requirements.txt
pytest
```

Every Section 2 hard limit and every Section 3 gate transition has a test
in `tests/`. If you change `hermes/limits.py` or `hermes/state.py`, add or
update the corresponding test first (execution-plan.md Section B
instruction 6).

## What this does NOT do yet

- No order placement or fund transfer of any kind, on any institution —
  `hermes/execution_guard.execute_live_order` always raises
  `NotImplementedError` by design, and neither the Plaid-backed accounts
  server nor the Robinhood MCP wiring (once added) ever expose an
  order/transfer tool to any role. Adding real execution is a separate,
  explicit task Diego signs off on, not a natural extension of this
  scaffold or of connecting more read-only data sources.
- Real market data and WF/Fidelity balances only work once you've done
  the one-time Alpaca/Plaid setup in step 2a above. Robinhood balance
  visibility additionally needs the manual MCP wiring described in
  `mcp_servers/robinhood/README.md`.
- No gate has been opened past Backtest. Open one with:
  `docker compose run --rm hermes-trading-chain python -m hermes.cli open-gate --gate paper --confirmed-by diego`
  (only Diego should ever run this).
