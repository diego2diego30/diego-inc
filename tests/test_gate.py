"""Section 3 coverage: gates are sequential, no skipping, and only Diego
opens them -- Hermes reports readiness, it does not self-promote.
"""
from __future__ import annotations

import pytest

from hermes.execution_guard import LiveExecutionNotAuthorized, assert_live_execution_authorized, execute_live_order
from hermes.state import GateState, InvalidGateTransition


class TestGateTransitions:
    def test_starts_at_backtest(self):
        assert GateState().gate == "backtest"

    def test_advances_one_step_at_a_time(self):
        state = GateState(gate="backtest")
        new_state = state.advance_to("paper", confirmed_by="diego")
        assert new_state.gate == "paper"
        assert new_state.opened_by == "diego"

    def test_cannot_skip_gates(self):
        state = GateState(gate="backtest")
        with pytest.raises(InvalidGateTransition):
            state.advance_to("shadow", confirmed_by="diego")

    def test_cannot_skip_straight_to_live(self):
        state = GateState(gate="backtest")
        with pytest.raises(InvalidGateTransition):
            state.advance_to("live_small", confirmed_by="diego")

    def test_cannot_go_backwards_via_advance_to(self):
        state = GateState(gate="paper")
        with pytest.raises(InvalidGateTransition):
            state.advance_to("backtest", confirmed_by="diego")

    def test_rejects_invalid_gate_name(self):
        state = GateState(gate="backtest")
        with pytest.raises(InvalidGateTransition):
            state.advance_to("yolo_mode", confirmed_by="diego")

    def test_requires_diego_confirmation(self):
        state = GateState(gate="backtest")
        with pytest.raises(InvalidGateTransition):
            state.advance_to("paper", confirmed_by="hermes")

    def test_requires_diego_confirmation_not_empty(self):
        state = GateState(gate="backtest")
        with pytest.raises(InvalidGateTransition):
            state.advance_to("paper", confirmed_by="")


class TestExecutionGuard:
    @pytest.mark.parametrize("gate", ["backtest", "paper", "shadow"])
    def test_blocks_live_execution_below_gate_4(self, gate):
        state = GateState(gate=gate, opened_by="diego")
        with pytest.raises(LiveExecutionNotAuthorized):
            assert_live_execution_authorized(state)

    @pytest.mark.parametrize("gate", ["live_small", "live_scaled"])
    def test_allows_check_to_pass_at_gate_4_plus_when_diego_confirmed(self, gate):
        state = GateState(gate=gate, opened_by="diego")
        assert_live_execution_authorized(state)  # does not raise

    def test_blocks_even_at_live_gate_if_not_diego_attributed(self):
        state = GateState(gate="live_small", opened_by="hermes")
        with pytest.raises(LiveExecutionNotAuthorized):
            assert_live_execution_authorized(state)

    def test_execute_live_order_always_raises_not_implemented(self):
        """No broker/order-placement code path exists yet, full stop --
        this test exists to fail loudly if anyone ever "fills in" this
        function without also updating this test and getting sign-off.
        """
        with pytest.raises(NotImplementedError):
            execute_live_order()
