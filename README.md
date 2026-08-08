# Diego, Inc. — Trading Instance

Self-hosted multi-agent orchestration for the trading system described in
[`docs/execution-plan.md`](docs/execution-plan.md) — the authoritative
spec for this repo. Read that document first; this README is just a map.

This repo is **one of two independent deployments**. The other,
Quinta55/business-ops, lives entirely in a separate repo
([`quinta55`](https://github.com/diego2diego30/quinta55)) with its own
Hermes process, credentials, and memory — nothing here is readable from
there, and nothing there is readable from here (execution-plan.md
Section A/6).

## Status

- **Gate:** 1 — Backtest (execution-plan.md Section 3). No gate advances
  without Diego running `hermes/cli.py open-gate` by hand.
- **Live execution:** not implemented. `hermes/execution_guard.py`'s
  `execute_live_order` always raises `NotImplementedError` — there is no
  code path to real capital yet, by design (Section B instruction 2).
- **Market data:** mock stub only (`mcp_servers/market_data/`).
- **Deployment:** built here, not yet deployed — see `deploy/README.md`
  for the runbook to run on the VPS (this session has no VPS/SSH access).

## Layout

```
trading/            # context read by every claude -p role invocation
  CLAUDE.md          # instance-wide standing instructions
  MEMORY.md          # auto-memory index
  memory/            # auto-memory topic files
  roles/<role>/CLAUDE.md
  logs/              # per-run reasoning logs (.jsonl, one per cycle)
  .mcp.json          # market-data MCP server wiring

hermes/              # orchestrator: config, state, hard limits, chain runner,
                      # Telegram bridge, CLI entrypoints
mcp_servers/market_data/   # stub MCP server (Section 4)
tests/               # Section 2 hard-limit + Section 3 gate coverage
deploy/              # Dockerfile, compose, systemd, cron, .env.example, runbook
docs/execution-plan.md   # the governing spec, verbatim
```

## Quickstart (local dev, no VPS needed)

```
pip install -r requirements.txt
pytest                       # 34 tests covering Section 2 + Section 3
```

Running the actual chain requires the Claude Code CLI installed and
authenticated, plus Telegram credentials — see `deploy/README.md`.

## What's still missing (do not fabricate — see execution-plan.md Section B instruction 4)

- Real Telegram bot token (you have one — wire it into `deploy/.env`,
  never commit it).
- Real market-data provider (currently a mock stub).
- Broker/exchange selection and credentials, for whenever Gate 4 is
  actually opened.
- A run on the actual VPS — everything above is built but undeployed.
