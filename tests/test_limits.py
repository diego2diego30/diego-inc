"""Section 2 coverage. Every box in the execution plan's hard-limits
checklist has at least one test here:

    [ ] Daily max-loss limit (hard stop, trading halts for the day if hit)
    [ ] Max position size as % of account
    [ ] Max number of open positions at once
    [ ] Circuit breaker: N consecutive losing trades -> pause, don't auto-resume
"""
from __future__ import annotations

import pytest

from hermes.config import LimitsConfig
from hermes.limits import LimitsEngine, Proposal
from hermes.state import AccountState


def make_engine(**account_overrides) -> LimitsEngine:
    config = LimitsConfig(
        daily_max_loss_pct=2.0,
        max_position_size_pct=5.0,
        max_open_positions=3,
        circuit_breaker_consecutive_losses=3,
    )
    account = AccountState(equity=100_000.0, **account_overrides)
    return LimitsEngine(config, account)


class TestDailyMaxLoss:
    def test_approves_when_under_daily_loss_limit(self):
        engine = make_engine(daily_pnl=-500.0)  # -0.5%, limit is -2%
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 2.0))
        assert decision.approved
        assert not decision.halted

    def test_hard_stop_when_daily_loss_limit_hit(self):
        engine = make_engine(daily_pnl=-2000.0)  # exactly -2% of 100k
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 2.0))
        assert not decision.approved
        assert decision.halted
        assert "daily max-loss" in decision.reasons[0].lower()

    def test_hard_stop_when_daily_loss_limit_exceeded(self):
        engine = make_engine(daily_pnl=-5000.0)  # -5%, way past -2%
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 1.0))
        assert not decision.approved
        assert decision.halted

    def test_trading_halted_today_flag_blocks_regardless_of_pnl_recovery(self):
        # Even if intraday P&L ticks back above the threshold, the halt
        # for the day stays set once tripped -- it's a hard stop, not a
        # live threshold re-check.
        engine = make_engine(daily_pnl=100.0, trading_halted_today=True)
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 1.0))
        assert not decision.approved
        assert decision.halted

    def test_record_trade_result_sets_halt_flag_on_breach(self):
        engine = make_engine(daily_pnl=0.0)
        engine.record_trade_result(-2500.0)  # -2.5% in one trade
        assert engine.account.trading_halted_today is True

    def test_record_trade_result_does_not_halt_under_limit(self):
        engine = make_engine(daily_pnl=0.0)
        engine.record_trade_result(-500.0)
        assert engine.account.trading_halted_today is False


class TestMaxPositionSize:
    def test_within_limit_passes_unchanged(self):
        engine = make_engine()
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 3.0))
        assert decision.approved
        assert decision.size_pct_of_account == 3.0

    def test_over_limit_is_shrunk_not_vetoed(self):
        engine = make_engine()
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 12.0))
        assert decision.approved
        assert decision.size_pct_of_account == 5.0
        assert any("shrunk" in r.lower() for r in decision.reasons)

    def test_zero_size_proposal_is_not_approved(self):
        engine = make_engine()
        decision = engine.evaluate_proposal(Proposal("SPY", "none", 0.0))
        assert not decision.approved


class TestMaxOpenPositions:
    def test_under_max_passes(self):
        engine = make_engine(open_positions=2)
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 2.0))
        assert decision.approved

    def test_at_max_is_blocked(self):
        engine = make_engine(open_positions=3)
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 2.0))
        assert not decision.approved
        assert "max open positions" in decision.reasons[0].lower()

    def test_over_max_is_blocked(self):
        engine = make_engine(open_positions=4)
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 2.0))
        assert not decision.approved


class TestCircuitBreaker:
    def test_not_tripped_below_threshold(self):
        engine = make_engine()
        engine.record_trade_result(-100.0)
        engine.record_trade_result(-100.0)
        assert engine.account.circuit_breaker_tripped is False
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 1.0))
        assert decision.approved

    def test_trips_at_n_consecutive_losses(self):
        engine = make_engine()
        engine.record_trade_result(-100.0)
        engine.record_trade_result(-100.0)
        engine.record_trade_result(-100.0)  # 3rd consecutive loss, limit=3
        assert engine.account.circuit_breaker_tripped is True

    def test_tripped_breaker_blocks_all_new_proposals(self):
        engine = make_engine(consecutive_losses=3, circuit_breaker_tripped=True)
        decision = engine.evaluate_proposal(Proposal("SPY", "long", 1.0))
        assert not decision.approved
        assert decision.halted
        assert "circuit breaker" in decision.reasons[0].lower()

    def test_a_win_resets_consecutive_loss_count(self):
        engine = make_engine()
        engine.record_trade_result(-100.0)
        engine.record_trade_result(-100.0)
        engine.record_trade_result(50.0)  # win breaks the streak
        assert engine.account.consecutive_losses == 0
        engine.record_trade_result(-100.0)
        engine.record_trade_result(-100.0)
        assert engine.account.circuit_breaker_tripped is False  # only 2 in a row since the win

    def test_does_not_auto_resume(self):
        """Section 2: 'pause and notify, don't auto-resume.' Nothing in
        record_trade_result, evaluate_proposal, or a fresh day rollover
        should ever clear circuit_breaker_tripped.
        """
        engine = make_engine(consecutive_losses=3, circuit_breaker_tripped=True)
        engine.account.roll_day_if_needed()
        assert engine.account.circuit_breaker_tripped is True
        # A subsequent winning trade also must not silently clear it --
        # only the explicit human-confirmed resume path may.
        engine.record_trade_result(500.0)
        assert engine.account.circuit_breaker_tripped is True

    def test_resume_requires_diego_confirmation(self):
        engine = make_engine(consecutive_losses=3, circuit_breaker_tripped=True)
        with pytest.raises(PermissionError):
            engine.resume_after_circuit_breaker(confirmed_by="hermes")
        assert engine.account.circuit_breaker_tripped is True  # unchanged

    def test_resume_succeeds_with_diego_confirmation(self):
        engine = make_engine(consecutive_losses=3, circuit_breaker_tripped=True)
        engine.resume_after_circuit_breaker(confirmed_by="diego")
        assert engine.account.circuit_breaker_tripped is False
        assert engine.account.consecutive_losses == 0
