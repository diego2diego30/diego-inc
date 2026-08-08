"""Section 2 hard limits — enforced in code, not just prompted.

This module is the single authority the Risk role's CLAUDE.md points to.
Every box in Section 2 must be implemented here AND covered by
tests/test_limits.py before any proposal can be marked approved, per
execution-plan.md Section B instruction 6 ("Every change touching Section
2's hard limits requires a corresponding test before being considered
complete.").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from hermes.config import LimitsConfig
from hermes.state import AccountState


@dataclass
class Proposal:
    instrument: str
    direction: str  # "long" | "short"
    size_pct_of_account: float


@dataclass
class Decision:
    approved: bool
    size_pct_of_account: float  # possibly shrunk from the proposal
    reasons: List[str] = field(default_factory=list)
    halted: bool = False  # daily halt or circuit breaker — distinct from a plain veto


class LimitsEngine:
    """Stateless logic over an explicit AccountState + LimitsConfig — no
    hidden globals, so it's trivially unit-testable and so Hermes can load
    fresh state every cron invocation without carrying process memory.
    """

    def __init__(self, config: LimitsConfig, account: AccountState):
        self.config = config
        self.account = account

    def evaluate_proposal(self, proposal: Proposal) -> Decision:
        reasons: List[str] = []

        # 1. Circuit breaker — checked first; a tripped breaker blocks
        #    everything else regardless of the other three checks.
        if self.account.circuit_breaker_tripped:
            return Decision(
                approved=False,
                size_pct_of_account=0.0,
                reasons=[
                    f"Circuit breaker tripped after "
                    f"{self.account.consecutive_losses} consecutive losing "
                    f"trades (limit: {self.config.circuit_breaker_consecutive_losses}). "
                    f"Paused. Requires Diego to manually resume — see "
                    f"hermes/cli.py resume-after-circuit-breaker. No automated "
                    f"path clears this flag."
                ],
                halted=True,
            )

        # 2. Daily max-loss — hard stop, halts trading for the rest of the day.
        daily_loss_limit = -abs(self.config.daily_max_loss_pct) / 100.0 * max(self.account.equity, 0.0)
        if self.account.trading_halted_today or (
            self.account.equity > 0 and self.account.daily_pnl <= daily_loss_limit
        ):
            return Decision(
                approved=False,
                size_pct_of_account=0.0,
                reasons=[
                    f"Daily max-loss limit hit: daily P&L "
                    f"{self.account.daily_pnl:.2f} <= limit {daily_loss_limit:.2f} "
                    f"({self.config.daily_max_loss_pct}% of equity "
                    f"{self.account.equity:.2f}). Trading halted for the day."
                ],
                halted=True,
            )

        # 3. Max open positions.
        if self.account.open_positions >= self.config.max_open_positions:
            return Decision(
                approved=False,
                size_pct_of_account=0.0,
                reasons=[
                    f"Max open positions reached: "
                    f"{self.account.open_positions} >= "
                    f"{self.config.max_open_positions}."
                ],
            )

        # 4. Max position size as % of account — shrink rather than
        #    outright veto, per the Risk role's "can veto or shrink" spec.
        size = proposal.size_pct_of_account
        if size > self.config.max_position_size_pct:
            reasons.append(
                f"Proposed size {size}% exceeds max "
                f"{self.config.max_position_size_pct}% of account; shrunk."
            )
            size = self.config.max_position_size_pct

        if size <= 0:
            return Decision(
                approved=False,
                size_pct_of_account=0.0,
                reasons=reasons + ["Proposed size is zero or negative after limit checks."],
            )

        reasons.append("Passed all Section 2 checks.")
        return Decision(approved=True, size_pct_of_account=size, reasons=reasons)

    def record_trade_result(self, pnl: float) -> AccountState:
        """Called after a fill (real, paper, or shadow-simulated) to keep
        daily P&L and the circuit breaker's consecutive-loss count current.
        Tripping the breaker sets a flag that only
        hermes/cli.py resume-after-circuit-breaker can clear, and that
        command requires an explicit, human-attributed confirmation —
        mirroring GateState.advance_to's "no automated path" guarantee.
        """
        self.account.daily_pnl += pnl
        self.account.equity += pnl

        if pnl < 0:
            self.account.consecutive_losses += 1
        else:
            self.account.consecutive_losses = 0

        if self.account.consecutive_losses >= self.config.circuit_breaker_consecutive_losses:
            self.account.circuit_breaker_tripped = True

        daily_loss_limit = -abs(self.config.daily_max_loss_pct) / 100.0 * max(self.account.equity, 0.0)
        if self.account.equity > 0 and self.account.daily_pnl <= daily_loss_limit:
            self.account.trading_halted_today = True

        return self.account

    def resume_after_circuit_breaker(self, confirmed_by: str) -> AccountState:
        if confirmed_by != "diego":
            raise PermissionError(
                "Circuit breaker resume requires explicit confirmation "
                "attributed to diego. Refusing an anonymous/automated resume."
            )
        self.account.circuit_breaker_tripped = False
        self.account.consecutive_losses = 0
        return self.account
