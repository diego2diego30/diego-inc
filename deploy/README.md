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

- No real market data (mock stub only — `mcp_servers/market_data/`).
- No broker/exchange integration, no order placement of any kind —
  `hermes/execution_guard.execute_live_order` always raises
  `NotImplementedError` by design. Adding a real one is a separate,
  explicit task Diego signs off on, not a natural extension of this
  scaffold.
- No gate has been opened past Backtest. Open one with:
  `docker compose run --rm hermes-trading-chain python -m hermes.cli open-gate --gate paper --confirmed-by diego`
  (only Diego should ever run this).
