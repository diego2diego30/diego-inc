"""Runs the Analyst -> Bull -> Bear -> Trader -> Risk -> PM chain via
headless `claude -p` subprocess calls, one process per role, each scoped
to its own CLAUDE.md and --allowedTools (Section 1: "No single agent sees
or does everything").

This is invoked by cron on the periodic-screener cadence (Section 4/5),
not run as a long-lived intraday loop.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Optional

from hermes.config import DEFAULT_MODEL_BY_ROLE, ROLE_CHAIN, LimitsConfig, Paths
from hermes.cost import BudgetExceeded, CostLedger, RunLock, cost_from_claude_response
from hermes.execution_guard import LiveExecutionNotAuthorized, assert_live_execution_authorized
from hermes.limits import Decision, LimitsEngine, Proposal
from hermes.logging_utils import RoleLogEntry, RunLogger
from hermes.state import AccountState, GateState

# Read-only for every role except Risk (which also gets the limits-check
# tool) and PM (decision-only, still no write/execution tools).
#
# Only Analyst gets the market-data and accounts MCP tools (Section 4) --
# Bull/Bear/Trader/Risk/PM reason over the Analyst's summary, not raw
# feeds, per trading/roles/analyst/CLAUDE.md ("you are the first link in
# the chain"). Both MCP servers (mcp_servers/market_data/,
# mcp_servers/accounts/) are read-only by construction; there is no
# order-placement or fund-transfer tool name to ever add here -- see
# hermes/execution_guard.py.
ROLE_ALLOWED_TOOLS = {
    "analyst": [
        "Read", "Grep", "Glob",
        "mcp__market-data__get_price",
        "mcp__market-data__get_technicals",
        "mcp__market-data__get_news",
        "mcp__accounts__get_account_balance",
        "mcp__accounts__get_investment_holdings",
    ],
    "bull": ["Read"],
    "bear": ["Read"],
    "trader": ["Read"],
    "risk": ["Read"],
    "pm": ["Read"],
}


class ChainError(RuntimeError):
    pass


@dataclass
class RoleResult:
    role: str
    text: str
    raw: dict


def _run_role(role: str, prompt: str, paths: Paths) -> RoleResult:
    role_dir = paths.roles_dir / role
    if not role_dir.exists():
        raise ChainError(f"No role directory for {role!r} at {role_dir}")

    model = DEFAULT_MODEL_BY_ROLE[role]
    allowed = ",".join(ROLE_ALLOWED_TOOLS[role])

    # cwd = the role's own directory so Claude Code's CLAUDE.md discovery
    # picks up roles/<role>/CLAUDE.md plus trading/CLAUDE.md from the
    # parent directory automatically. Nothing under other roles/, and
    # nothing under quinta55/, is reachable from this cwd.
    cmd = [
        "claude", "-p", prompt,
        "--model", model,
        "--allowedTools", allowed,
        "--output-format", "json",
    ]
    proc = subprocess.run(cmd, cwd=str(role_dir), capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise ChainError(f"Role {role!r} failed (exit {proc.returncode}): {proc.stderr[:2000]}")

    try:
        raw = json.loads(proc.stdout)
        text = raw.get("result", proc.stdout)
    except json.JSONDecodeError:
        raw = {"raw_stdout": proc.stdout}
        text = proc.stdout

    return RoleResult(role=role, text=text, raw=raw)


def run_chain(
    instrument_universe: str,
    limits_config: Optional[LimitsConfig] = None,
    paths: Optional[Paths] = None,
) -> dict:
    """One full cycle. Returns a summary dict suitable for the Telegram
    status push. Never raises to skip logging — logs partial progress even
    on failure, per Section 4.
    """
    paths = paths or Paths()
    limits_config = limits_config or LimitsConfig()
    logger = RunLogger(paths=paths)
    ledger = CostLedger(paths=paths)

    gate_state = GateState.load()
    account = AccountState.load().roll_day_if_needed()
    account.save()

    logger.log_event("chain_start", f"instrument_universe={instrument_universe} gate={gate_state.gate}")

    run_cost_usd = 0.0

    def _bill(role: str, result: "RoleResult") -> None:
        nonlocal run_cost_usd
        usage = cost_from_claude_response(role, DEFAULT_MODEL_BY_ROLE[role], result.raw, run_id=logger.run_id)
        ledger.record(usage)
        run_cost_usd += usage.cost_usd
        # Checked after every role, not just at chain end, so a single
        # pathological call is cut off mid-chain instead of after all six
        # roles have already billed.
        ledger.assert_run_within_cap(run_cost_usd)

    try:
        # Section 5: a hard spend cap, checked before any billed call is
        # made -- inside the try so a tripped cap is logged as
        # budget_blocked, not just raised bare.
        ledger.assert_within_budget()

        # RunLock guards the entire billed portion of the chain -- see
        # hermes/cost.py: a hung `claude -p` call under an overlapping
        # cron/manual trigger would otherwise accumulate one billing
        # process per trigger.
        with RunLock(paths=paths):
            analyst = _run_role("analyst", f"Analyze current market state for: {instrument_universe}", paths)
            logger.log_role(RoleLogEntry(role="analyst", model=DEFAULT_MODEL_BY_ROLE["analyst"],
                                          reasoning=analyst.text, output=analyst.raw))
            _bill("analyst", analyst)

            bull = _run_role("bull", f"Analyst output:\n{analyst.text}\n\nBuild the strongest case FOR a position.", paths)
            logger.log_role(RoleLogEntry(role="bull", model=DEFAULT_MODEL_BY_ROLE["bull"],
                                          reasoning=bull.text, output=bull.raw))
            _bill("bull", bull)

            bear = _run_role("bear", f"Analyst output:\n{analyst.text}\n\nBuild the strongest case AGAINST a position.", paths)
            logger.log_role(RoleLogEntry(role="bear", model=DEFAULT_MODEL_BY_ROLE["bear"],
                                          reasoning=bear.text, output=bear.raw))
            _bill("bear", bear)

            trader = _run_role(
                "trader",
                f"Bull case:\n{bull.text}\n\nBear case:\n{bear.text}\n\n"
                f"Propose a specific position and size (sized for a longer hold).",
                paths,
            )
            logger.log_role(RoleLogEntry(role="trader", model=DEFAULT_MODEL_BY_ROLE["trader"],
                                          reasoning=trader.text, output=trader.raw))
            _bill("trader", trader)

            # Section 2: hard limits are enforced here in code, not left to
            # the Risk role's prompt to reason about correctly.
            proposal = _parse_proposal(trader.text, instrument_universe)
            engine = LimitsEngine(limits_config, account)
            decision = engine.evaluate_proposal(proposal)
            account.save()
            logger.log_event("limits_decision", json.dumps({
                "approved": decision.approved,
                "size_pct_of_account": decision.size_pct_of_account,
                "reasons": decision.reasons,
                "halted": decision.halted,
            }))

            risk = _run_role(
                "risk",
                f"Trader proposal:\n{trader.text}\n\n"
                f"Hard-limit engine decision (authoritative, do not override):\n{decision}",
                paths,
            )
            logger.log_role(RoleLogEntry(role="risk", model=DEFAULT_MODEL_BY_ROLE["risk"],
                                          reasoning=risk.text, output=risk.raw))
            _bill("risk", risk)

            pm = _run_role(
                "pm",
                f"Full chain for this cycle:\nAnalyst: {analyst.text}\nBull: {bull.text}\nBear: {bear.text}\n"
                f"Trader: {trader.text}\nRisk manager: {risk.text}\nLimits decision: {decision}\n\n"
                f"Approve, reject, or escalate.",
                paths,
            )
            logger.log_role(RoleLogEntry(role="pm", model=DEFAULT_MODEL_BY_ROLE["pm"],
                                          reasoning=pm.text, output=pm.raw))
            _bill("pm", pm)

            # Even a PM "approve" never reaches real execution without an
            # explicit, human-confirmed Gate 4+. This call exists so that
            # future real-execution wiring has exactly one place to hook in,
            # and so today it visibly (and loudly) refuses.
            try:
                assert_live_execution_authorized(gate_state)
                live_authorized = True
            except LiveExecutionNotAuthorized as exc:
                live_authorized = False
                logger.log_event("live_execution_blocked", str(exc))

        logger.log_event(
            "chain_end",
            f"decision_approved={decision.approved} live_authorized={live_authorized} "
            f"run_cost_usd={run_cost_usd:.4f}",
        )

        return {
            "gate": gate_state.gate,
            "decision_approved": decision.approved,
            "decision_reasons": decision.reasons,
            "live_authorized": live_authorized,
            "pm_summary": pm.text,
            "log_path": str(logger.log_path),
            "run_cost_usd": run_cost_usd,
        }
    except BudgetExceeded as exc:
        logger.log_event("budget_blocked", str(exc))
        raise
    except Exception as exc:  # noqa: BLE001 - deliberately broad: log then re-raise
        logger.log_event("chain_error", str(exc))
        raise


def _parse_proposal(trader_text: str, instrument_universe: str) -> Proposal:
    """Best-effort structured parse of the Trader's free-text proposal.
    Replace with a JSON-contract once the Trader role's output format is
    finalized against real runs — kept deliberately simple for the
    scaffold stage rather than over-built ahead of real usage.
    """
    try:
        data = json.loads(trader_text)
        return Proposal(
            instrument=data.get("instrument", instrument_universe),
            direction=data.get("direction", "long"),
            size_pct_of_account=float(data.get("size_pct_of_account", 0.0)),
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        # No parseable proposal (e.g. Trader recommended no action) -> a
        # zero-size proposal that the limits engine will pass through as
        # "nothing to do" rather than the orchestrator guessing a size.
        return Proposal(instrument=instrument_universe, direction="none", size_pct_of_account=0.0)
