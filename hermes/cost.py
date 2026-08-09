"""Section 5 cost control — token accounting, monthly projection, and the
hard spend caps that keep a bug in the cron loop from running up an
unbounded bill.

execution-plan.md Section 5: "Set a hard monthly spend cap on API/usage-
credit overflow, same discipline as the trading hard-limits in Section 2.
A bug in the cron loop should hit a billing ceiling, not an unbounded
bill." and "Re-check actual usage after week one. Any estimate below is a
planning number, not a bill -- pull real token counts from your first week
of runs and recalibrate."

Cost is taken from what the Claude Code CLI itself reports per call
(`total_cost_usd` in its `--output-format json` response), not computed
from a hard-coded price table -- so these numbers can't silently drift out
of date when Anthropic changes pricing. PRICE_PER_MTOK below is only a
fallback for calls that report no cost, and is labelled with the date it
was taken.

Same enforcement philosophy as limits.py: no override parameter, no
env-var escape hatch, and no code path that lifts a cap based on model
output. A tripped cap requires an explicit, human-attributed reset.
"""
from __future__ import annotations

import json
import os
from calendar import monthrange
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

from hermes.config import Paths


def _today_utc() -> date:
    """UTC calendar date -- the VPS clock runs on UTC (confirmed via
    `timedatectl`), and every UsageRecord timestamp below is UTC too.
    Comparing a UTC timestamp against a *local* `date.today()` would
    undercount runs_today() right around UTC midnight -- for US
    timezones, that's an afternoon/evening window, not a rare edge case.
    """
    return datetime.now(timezone.utc).date()

# Fallback only -- used when a `claude -p` response reports no
# total_cost_usd. Prices in USD per million tokens, from
# platform.claude.com as of 2026-08-08. Cache reads bill at ~0.1x base
# input; 5-minute-TTL cache writes at ~1.25x.
PRICE_PER_MTOK = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
}
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


class BudgetExceeded(RuntimeError):
    """Raised instead of starting/continuing a run that would spend past a
    configured cap. Deliberately a hard stop, not a warning.
    """


@dataclass(frozen=True)
class BudgetConfig:
    """Section 5 spend caps. Defaults sized around the plan's own estimate
    (~$5-15/mo for the recommended daily-screener cadence, inside the $20
    Agent SDK credit) with headroom, so a normal month never trips them and
    a runaway loop does.
    """

    monthly_usd_cap: float = field(
        default_factory=lambda: float(os.environ.get("MONTHLY_USD_CAP", "20.0"))
    )
    per_run_usd_cap: float = field(
        default_factory=lambda: float(os.environ.get("PER_RUN_USD_CAP", "2.0"))
    )
    max_runs_per_day: int = field(
        default_factory=lambda: int(os.environ.get("MAX_RUNS_PER_DAY", "4"))
    )


@dataclass
class UsageRecord:
    """One `claude -p` call. Written append-only so a crash mid-chain still
    leaves the spend that already happened on disk -- an unrecorded call is
    a bill you can't see.
    """

    role: str
    model: str
    cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    run_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )


def cost_from_claude_response(role: str, model: str, raw: dict, run_id: str = "") -> UsageRecord:
    """Build a UsageRecord from a `claude -p --output-format json` payload.

    Uses the CLI's own `total_cost_usd` when present. Falls back to
    PRICE_PER_MTOK only when the CLI reports nothing -- and returns 0.0
    rather than guessing if the model isn't in the table, because a
    fabricated cost is worse than a visibly missing one (Section B
    instruction 4).
    """
    usage = raw.get("usage") or {}
    record = UsageRecord(
        role=role,
        model=model,
        cost_usd=0.0,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
        run_id=run_id,
    )

    reported = raw.get("total_cost_usd")
    if isinstance(reported, (int, float)) and reported > 0:
        record.cost_usd = float(reported)
        return record

    prices = PRICE_PER_MTOK.get(model)
    if not prices:
        return record  # cost_usd stays 0.0 -- unknown, not invented

    record.cost_usd = (
        record.input_tokens * prices["input"]
        + record.cache_read_input_tokens * prices["input"] * CACHE_READ_MULTIPLIER
        + record.cache_creation_input_tokens * prices["input"] * CACHE_WRITE_MULTIPLIER
        + record.output_tokens * prices["output"]
    ) / 1_000_000
    return record


@dataclass
class CostReport:
    month: str
    month_to_date_usd: float
    projected_month_usd: float
    monthly_cap_usd: float
    pct_of_cap: float
    runs_this_month: int
    runs_today: int
    max_runs_per_day: int
    total_tokens_this_month: int
    by_role: dict
    days_elapsed: int
    days_in_month: int

    def as_text(self) -> str:
        """Plain-text summary for Telegram / CLI. Kept terse enough to read
        on a phone.
        """
        lines = [
            f"Cost report -- {self.month}",
            f"Spent so far: ${self.month_to_date_usd:.2f}",
            f"Projected month: ${self.projected_month_usd:.2f}",
            f"Cap: ${self.monthly_cap_usd:.2f} ({self.pct_of_cap:.0f}% used)",
            f"Runs: {self.runs_this_month} this month, {self.runs_today} today "
            f"(daily limit {self.max_runs_per_day})",
            f"Tokens: {self.total_tokens_this_month:,}",
        ]
        if self.by_role:
            lines.append("By role:")
            for role, cost in sorted(self.by_role.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {role}: ${cost:.2f}")
        if self.days_elapsed < 8:
            lines.append(
                "Note: projection is a straight line from a short sample. "
                "Section 5 says recalibrate after a full week of real runs."
            )
        return "\n".join(lines)


class CostLedger:
    """Append-only JSONL ledger, one file per month under the Hermes data
    volume. Monthly files keep the read path cheap and make an old month
    trivially archivable.
    """

    def __init__(self, paths: Optional[Paths] = None, config: Optional[BudgetConfig] = None):
        self.paths = paths or Paths()
        self.config = config or BudgetConfig()
        self.ledger_dir = self.paths.data_dir / "cost"
        self.ledger_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_month(self, month: str) -> Path:
        return self.ledger_dir / f"{month}.jsonl"

    @staticmethod
    def _current_month() -> str:
        return _today_utc().strftime("%Y-%m")

    def record(self, usage: UsageRecord) -> None:
        with self._path_for_month(self._current_month()).open("a") as f:
            f.write(json.dumps(asdict(usage)) + "\n")

    def records_for_month(self, month: Optional[str] = None) -> List[UsageRecord]:
        path = self._path_for_month(month or self._current_month())
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                out.append(UsageRecord(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue  # a torn final line from a crash shouldn't break reporting
        return out

    def month_to_date_usd(self, month: Optional[str] = None) -> float:
        return sum(r.cost_usd for r in self.records_for_month(month))

    def runs_today(self) -> int:
        today = _today_utc().isoformat()
        return len({
            r.run_id
            for r in self.records_for_month()
            if r.run_id and r.timestamp.startswith(today)
        })

    def report(self, month: Optional[str] = None) -> CostReport:
        month = month or self._current_month()
        records = self.records_for_month(month)
        mtd = sum(r.cost_usd for r in records)

        year, mon = (int(x) for x in month.split("-"))
        days_in_month = monthrange(year, mon)[1]
        today = _today_utc()
        # A past month is complete; the current month is partial.
        days_elapsed = today.day if (today.year, today.month) == (year, mon) else days_in_month
        days_elapsed = max(days_elapsed, 1)
        projected = mtd / days_elapsed * days_in_month

        by_role: dict = {}
        for r in records:
            by_role[r.role] = by_role.get(r.role, 0.0) + r.cost_usd

        cap = self.config.monthly_usd_cap
        return CostReport(
            month=month,
            month_to_date_usd=mtd,
            projected_month_usd=projected,
            monthly_cap_usd=cap,
            pct_of_cap=(mtd / cap * 100.0) if cap > 0 else 0.0,
            runs_this_month=len({r.run_id for r in records if r.run_id}),
            runs_today=self.runs_today(),
            max_runs_per_day=self.config.max_runs_per_day,
            total_tokens_this_month=sum(r.total_tokens for r in records),
            by_role=by_role,
            days_elapsed=days_elapsed,
            days_in_month=days_in_month,
        )

    def assert_within_budget(self) -> None:
        """Called before a chain starts. Raises rather than returning a
        flag so there is no way to proceed by ignoring a return value.
        """
        mtd = self.month_to_date_usd()
        if mtd >= self.config.monthly_usd_cap:
            raise BudgetExceeded(
                f"Monthly spend cap reached: ${mtd:.2f} >= "
                f"${self.config.monthly_usd_cap:.2f} (MONTHLY_USD_CAP). "
                f"No further chain runs this month. Raise the cap in "
                f"deploy/.env deliberately, or wait for the month to roll."
            )

        runs = self.runs_today()
        if runs >= self.config.max_runs_per_day:
            raise BudgetExceeded(
                f"Daily run limit reached: {runs} >= "
                f"{self.config.max_runs_per_day} (MAX_RUNS_PER_DAY). This "
                f"exists to stop a misconfigured cron or a retry loop from "
                f"firing the chain repeatedly."
            )

    def assert_run_within_cap(self, run_cost_usd: float) -> None:
        """Called between roles mid-chain, so a single pathological run is
        cut off partway rather than after all six roles have billed.
        """
        if run_cost_usd >= self.config.per_run_usd_cap:
            raise BudgetExceeded(
                f"Single-run cost cap reached: ${run_cost_usd:.2f} >= "
                f"${self.config.per_run_usd_cap:.2f} (PER_RUN_USD_CAP). "
                f"Aborting this chain mid-run."
            )


class RunLock:
    """Prevents overlapping chain runs.

    The Section 5 failure this guards against is specific: cron fires on a
    fixed schedule regardless of whether the previous run finished. A chain
    that hangs (a `claude -p` call waiting on the network, say) would
    otherwise accumulate one live process per cron tick, each billing.

    Stale locks are reclaimed after `stale_after_seconds` so a hard crash
    can't wedge the schedule permanently.
    """

    def __init__(self, paths: Optional[Paths] = None, stale_after_seconds: int = 3600):
        self.paths = paths or Paths()
        self.lock_path = self.paths.data_dir / "chain.lock"
        self.stale_after_seconds = stale_after_seconds

    def acquire(self) -> None:
        if self.lock_path.exists():
            try:
                held = json.loads(self.lock_path.read_text())
                started = datetime.fromisoformat(held["started_at"])
                age = (datetime.now(timezone.utc) - started).total_seconds()
            except (json.JSONDecodeError, KeyError, ValueError):
                age = self.stale_after_seconds + 1  # unreadable lock == stale

            if age <= self.stale_after_seconds:
                raise BudgetExceeded(
                    f"A chain run is already in progress (lock held for "
                    f"{age:.0f}s, pid {held.get('pid', '?')}). Refusing to "
                    f"start an overlapping run."
                )

        self.lock_path.write_text(json.dumps({
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }))

    def release(self) -> None:
        self.lock_path.unlink(missing_ok=True)

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()
