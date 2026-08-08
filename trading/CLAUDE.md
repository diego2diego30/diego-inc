# Trading Instance — Standing Instructions

This file is read as context by every `claude -p` invocation in the trading
instance (all six roles) and by Hermes itself. It is the top-level policy
layer; role-specific `CLAUDE.md` files under `roles/<role>/` narrow it
further and must never contradict it.

## What this instance is

A periodic screener — daily/weekly cadence, longer holding periods — not an
intraday day-trading loop. See `docs/execution-plan.md` Section 1 for the
evidence behind that choice. If you find yourself about to propose or reason
about sub-daily polling or same-day round-trips, stop: that is out of scope
for this instance.

## Isolation boundary (do not cross)

- Nothing under `/opt/ecosystem/trading/` is readable from, writable by, or
  referenced by the Quinta55 instance, and vice versa.
- No personal/admin content (Poke's domain) belongs here.
- No credential, API key, or account identifier belonging to Quinta55 may
  appear in this tree, in logs under `trading/logs/`, or in memory under
  `trading/memory/`.

## Gate status governs everything

Current gate (source of truth: `hermes/state.py` gate-state file on the VPS,
mirrored in `MEMORY.md`): **Gate 1 — Backtest.** See
`docs/execution-plan.md` Section 3.

Regardless of what any role concludes, agents in this instance:

- MAY produce proposals, analysis, backtests, and paper/shadow-mode output.
- MUST NOT call, invoke, or recommend invoking any code path that places a
  real order, moves real capital, or writes to a live brokerage/exchange
  account. That code path does not exist in this codebase (see
  `hermes/limits.py`) until Diego explicitly confirms Gate 4 in writing.
- MUST NOT reason around this by suggesting workarounds, manual overrides,
  or "just this once" exceptions. If a role's output implies live execution
  is warranted, the correct action is to say so in the reasoning log and
  stop — not to act on it.

## Hard limits are enforced in code, not by these instructions

`hermes/limits.py` is the authority for daily max-loss, max position size,
max open positions, and the consecutive-loss circuit breaker (Section 2 of
the execution plan). Every role must treat a rejection from that engine as
final. Do not attempt to reconstruct or bypass its logic from within a
prompt.

## Reasoning logs

Every chain run writes one log entry per role to `trading/logs/`, per
Section 4 of the execution plan — not just the Portfolio Manager's final
call. See `hermes/logging_utils.py`. If you are a role agent, assume your
full reasoning is being captured verbatim; write it as if Diego will read
it after a bad trade to figure out where the chain went wrong.

## Memory discipline

`MEMORY.md` is the auto-memory index (capped ~200 lines / 25KB on load).
Only durable, cross-cycle facts belong there — current gate, hard-limit
values, structural lessons about setups the Analyst flags well or poorly.
Do not write per-cycle transient data (today's price, today's proposal)
into memory — that belongs in `logs/`. Per Section 6, auto-memory additions
should be reviewed periodically by Diego, not trusted as silently correct;
if you add something to memory, make it easy to audit (short, dated,
attributable to a specific role/run).

## Social sentiment (X/social feeds)

If wired in, treat as one weak, low-confidence input to the Analyst's
output for the Bull/Bear debate — never a standalone trigger, never
something the Trader acts on directly. See Section 1 of the execution plan.
