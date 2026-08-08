# Trading Instance — Auto-Memory Index

Auto-memory index for the trading instance. Kept under ~200 lines / 25KB so
it loads cheaply on every `claude -p` invocation. Topic files this index
points to live in `memory/`. No personal-life content, no Quinta55/Diego
Inc. business content — trading only.

## Current state

- **Gate:** 1 — Backtest (see `docs/execution-plan.md` Section 3). Not
  advanced by any agent; Diego opens each gate explicitly.
- **Hard limits:** defined in `hermes/limits.py` / loaded from
  `deploy/.env` on the VPS. See that file for current numeric values —
  this index intentionally does not duplicate numbers that can drift out
  of sync with the enforced config.
- **Circuit breaker state:** not tripped.
- **Live execution:** disabled at the code level (no order-placement path
  exists yet). Do not describe this as "temporarily disabled" — it is
  unimplemented by design until Gate 4.

## Topic files

(none yet — created by Hermes as patterns accumulate; e.g.
`memory/analyst-setups.md`, `memory/backtest-notes.md`)

## Review log

Per Section 6: auto-memory additions here should be reviewed by Diego
periodically, not trusted as silently correct. Log each review below.

| Date | Reviewed by | Notes |
|---|---|---|
| — | — | Instance just scaffolded; nothing to review yet. |
