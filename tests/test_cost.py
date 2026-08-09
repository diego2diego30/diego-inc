"""Section 5 coverage: on-demand cost reporting and the hard spend
safeguards (monthly cap, per-run cap, daily run limit, overlapping-run
lock) that keep a bug in the cron loop from running up an unbounded bill.
"""
from __future__ import annotations

import time

import pytest

from hermes.cost import (
    BudgetConfig,
    BudgetExceeded,
    CostLedger,
    RunLock,
    UsageRecord,
    cost_from_claude_response,
)


class TestCostFromClaudeResponse:
    def test_uses_the_clis_own_reported_cost(self):
        raw = {
            "total_cost_usd": 0.0123,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        record = cost_from_claude_response("analyst", "claude-haiku-4-5-20251001", raw, run_id="r1")
        assert record.cost_usd == 0.0123
        assert record.input_tokens == 100
        assert record.output_tokens == 50
        assert record.role == "analyst"
        assert record.run_id == "r1"

    def test_falls_back_to_price_table_when_cli_reports_no_cost(self):
        raw = {"usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
        record = cost_from_claude_response("trader", "claude-sonnet-5", raw)
        # 1M input @ $3/MTok + 1M output @ $15/MTok = $18
        assert record.cost_usd == pytest.approx(18.0)

    def test_falls_back_correctly_for_haiku(self):
        raw = {"usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
        record = cost_from_claude_response("analyst", "claude-haiku-4-5-20251001", raw)
        # 1M input @ $1/MTok + 1M output @ $5/MTok = $6
        assert record.cost_usd == pytest.approx(6.0)

    def test_cache_tokens_priced_at_their_own_multipliers(self):
        raw = {
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 1_000_000,
                "cache_read_input_tokens": 1_000_000,
            }
        }
        record = cost_from_claude_response("analyst", "claude-sonnet-5", raw)
        # cache write: 1M * $3 * 1.25 = $3.75; cache read: 1M * $3 * 0.1 = $0.30
        assert record.cost_usd == pytest.approx(3.75 + 0.30)

    def test_unknown_model_reports_zero_not_a_guess(self):
        raw = {"usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
        record = cost_from_claude_response("analyst", "some-future-model", raw)
        assert record.cost_usd == 0.0

    def test_zero_reported_cost_falls_back_rather_than_trusting_a_literal_zero(self):
        # A `total_cost_usd: 0` on a call that clearly used tokens is more
        # likely a missing field than a free call -- fall back to the
        # price table instead of recording a silent $0.
        raw = {
            "total_cost_usd": 0,
            "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
        }
        record = cost_from_claude_response("trader", "claude-sonnet-5", raw)
        assert record.cost_usd == pytest.approx(18.0)


class TestCostLedger:
    def test_records_and_sums_month_to_date(self):
        ledger = CostLedger()
        ledger.record(UsageRecord(role="analyst", model="claude-haiku-4-5-20251001", cost_usd=0.10, run_id="r1"))
        ledger.record(UsageRecord(role="trader", model="claude-sonnet-5", cost_usd=0.25, run_id="r1"))
        assert ledger.month_to_date_usd() == pytest.approx(0.35)

    def test_report_breaks_down_by_role(self):
        ledger = CostLedger()
        ledger.record(UsageRecord(role="analyst", model="claude-haiku-4-5-20251001", cost_usd=0.10, run_id="r1"))
        ledger.record(UsageRecord(role="analyst", model="claude-haiku-4-5-20251001", cost_usd=0.05, run_id="r2"))
        ledger.record(UsageRecord(role="trader", model="claude-sonnet-5", cost_usd=0.25, run_id="r1"))
        report = ledger.report()
        assert report.by_role["analyst"] == pytest.approx(0.15)
        assert report.by_role["trader"] == pytest.approx(0.25)
        assert report.runs_this_month == 2  # distinct run_ids

    def test_report_projects_linearly_from_days_elapsed(self):
        config = BudgetConfig(monthly_usd_cap=100.0)
        ledger = CostLedger(config=config)
        ledger.record(UsageRecord(role="analyst", model="claude-haiku-4-5-20251001", cost_usd=10.0, run_id="r1"))
        report = ledger.report()
        # projected = mtd / days_elapsed * days_in_month; with days_elapsed
        # clamped to >=1 this is always >= mtd for day 1
        assert report.projected_month_usd >= report.month_to_date_usd
        assert report.monthly_cap_usd == 100.0
        assert report.pct_of_cap == pytest.approx(10.0)

    def test_empty_ledger_reports_zero_not_an_error(self):
        report = CostLedger().report()
        assert report.month_to_date_usd == 0.0
        assert report.runs_this_month == 0
        assert report.by_role == {}

    def test_as_text_includes_cap_and_spend(self):
        config = BudgetConfig(monthly_usd_cap=20.0)
        ledger = CostLedger(config=config)
        ledger.record(UsageRecord(role="analyst", model="claude-haiku-4-5-20251001", cost_usd=1.0, run_id="r1"))
        text = ledger.report().as_text()
        assert "$1.00" in text
        assert "$20.00" in text


class TestBudgetCaps:
    def test_assert_within_budget_passes_under_cap(self):
        config = BudgetConfig(monthly_usd_cap=20.0, max_runs_per_day=10)
        ledger = CostLedger(config=config)
        ledger.record(UsageRecord(role="analyst", model="claude-haiku-4-5-20251001", cost_usd=5.0, run_id="r1"))
        ledger.assert_within_budget()  # should not raise

    def test_assert_within_budget_raises_when_monthly_cap_hit(self):
        config = BudgetConfig(monthly_usd_cap=10.0, max_runs_per_day=10)
        ledger = CostLedger(config=config)
        ledger.record(UsageRecord(role="analyst", model="claude-haiku-4-5-20251001", cost_usd=10.0, run_id="r1"))
        with pytest.raises(BudgetExceeded):
            ledger.assert_within_budget()

    def test_assert_within_budget_raises_when_daily_run_limit_hit(self):
        config = BudgetConfig(monthly_usd_cap=1000.0, max_runs_per_day=2)
        ledger = CostLedger(config=config)
        ledger.record(UsageRecord(role="analyst", model="claude-haiku-4-5-20251001", cost_usd=0.01, run_id="run-a"))
        ledger.record(UsageRecord(role="analyst", model="claude-haiku-4-5-20251001", cost_usd=0.01, run_id="run-b"))
        with pytest.raises(BudgetExceeded):
            ledger.assert_within_budget()

    def test_assert_run_within_cap_raises_when_single_run_too_expensive(self):
        config = BudgetConfig(per_run_usd_cap=1.0)
        ledger = CostLedger(config=config)
        with pytest.raises(BudgetExceeded):
            ledger.assert_run_within_cap(1.5)

    def test_assert_run_within_cap_passes_under_cap(self):
        config = BudgetConfig(per_run_usd_cap=1.0)
        ledger = CostLedger(config=config)
        ledger.assert_run_within_cap(0.5)  # should not raise

    def test_no_override_path_exists_on_budget_config(self):
        # Section 5 (mirroring Section 2's hard-limits discipline): no
        # override parameter, no escape hatch. Confirm assert_within_budget
        # takes no arguments that could bypass a tripped cap.
        import inspect
        sig = inspect.signature(CostLedger.assert_within_budget)
        assert list(sig.parameters) == ["self"]


class TestRunLock:
    def test_acquire_then_release_allows_a_second_run(self):
        lock = RunLock()
        lock.acquire()
        lock.release()
        lock.acquire()  # should not raise -- lock was released
        lock.release()

    def test_overlapping_acquire_raises(self):
        lock = RunLock()
        lock.acquire()
        try:
            with pytest.raises(BudgetExceeded):
                RunLock().acquire()
        finally:
            lock.release()

    def test_context_manager_releases_on_exit(self):
        with RunLock():
            pass
        RunLock().acquire()  # should not raise -- prior lock released on exit
        RunLock().release()

    def test_context_manager_releases_even_on_exception(self):
        with pytest.raises(ValueError):
            with RunLock():
                raise ValueError("boom")
        RunLock().acquire()  # lock must not still be held
        RunLock().release()

    def test_stale_lock_is_reclaimed(self):
        lock = RunLock(stale_after_seconds=0)
        lock.acquire()
        time.sleep(0.01)
        # A second lock with the same (already-expired) staleness window
        # should reclaim rather than raise.
        RunLock(stale_after_seconds=0).acquire()
