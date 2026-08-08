"""Execution guard — the single chokepoint standing between a PM
"approved" decision and anything touching real capital.

execution-plan.md Section B instruction 2: "No live-execution code path
(real trades, real financial transactions, real business-system writes)
under any circumstances until Section 2's hard limits are implemented and
tested, and Section 3's gate 4 is explicitly reached and confirmed by
Diego."

There is deliberately no broker/exchange order-placement function anywhere
in this codebase yet — not stubbed, not behind a flag, not commented out.
`execute_live_order` below always raises. When Diego is ready to open
Gate 4 and provides real broker credentials + an MCP/API integration, that
integration should call through this guard, not around it, and this
guard's checks should get *stricter* over time, never weaker.
"""
from __future__ import annotations

from hermes.state import GateState


class LiveExecutionNotAuthorized(RuntimeError):
    pass


def assert_live_execution_authorized(gate_state: GateState) -> None:
    """Raises unless every one of these is true:
    - gate is live_small or live_scaled (Section 3, gates 4-5)
    - the gate transition was itself attributed to diego (see
      GateState.advance_to, which refuses anything else)

    This function intentionally has no "override" parameter, no env-var
    escape hatch, and no code path that flips it based on model output.
    """
    if gate_state.gate not in ("live_small", "live_scaled"):
        raise LiveExecutionNotAuthorized(
            f"Current gate is {gate_state.gate!r}. Live execution requires "
            f"gate live_small or live_scaled, opened explicitly by Diego "
            f"via hermes/cli.py open-gate. Proposal/paper/shadow only."
        )
    if gate_state.opened_by != "diego":
        raise LiveExecutionNotAuthorized(
            "Gate state was not attributed to an explicit diego "
            "confirmation. Refusing to treat this as live-authorized."
        )


def execute_live_order(*_args, **_kwargs):
    """Not implemented. Do not implement this by wiring it directly to a
    broker call — first confirm with Diego per Section B instruction 2,
    add the broker MCP integration per Section 4, and route the call
    through `assert_live_execution_authorized` first.
    """
    raise NotImplementedError(
        "No live-execution code path exists in this codebase. See "
        "docs/execution-plan.md Section B instruction 2 and Section 3 "
        "gate 4. This is intentional, not a bug."
    )
