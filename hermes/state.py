"""Persisted state for gate progression and account/risk tracking.

Stored as JSON under `Paths().data_dir` (Hermes's own data volume, separate
from `trading/` per execution-plan.md Section A). Small and inspectable by
design — Diego should be able to `cat` these files on the VPS and
understand exactly what the system thinks is true.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from hermes.config import GATES, Paths


class InvalidGateTransition(RuntimeError):
    pass


@dataclass
class GateState:
    """Section 3. Sequential, no skipping, opened only by Diego."""

    gate: str = "backtest"
    opened_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    opened_by: str = "diego"  # every transition must be attributed; never "system"

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "GateState":
        path = path or (Paths().data_dir / "gate_state.json")
        if not path.exists():
            return cls()
        return cls(**json.loads(path.read_text()))

    def save(self, path: Optional[Path] = None) -> None:
        path = path or (Paths().data_dir / "gate_state.json")
        path.write_text(json.dumps(asdict(self), indent=2))

    def advance_to(self, new_gate: str, confirmed_by: str) -> "GateState":
        """The only way this codebase changes gates. Called exclusively
        from a human-invoked CLI (`hermes/cli.py open-gate`), never from
        the orchestrator, PM role output, or any automated path — PM can
        recommend, it cannot self-promote (Section 3: "You decide when
        each gate opens. Hermes reports readiness; it does not
        self-promote through the gates.").
        """
        if new_gate not in GATES:
            raise InvalidGateTransition(f"{new_gate!r} is not a valid gate: {GATES}")
        current_idx = GATES.index(self.gate)
        new_idx = GATES.index(new_gate)
        if new_idx != current_idx + 1:
            raise InvalidGateTransition(
                f"Cannot jump from {self.gate!r} to {new_gate!r}. Gates are "
                f"sequential, no skipping: {GATES}"
            )
        if confirmed_by != "diego":
            raise InvalidGateTransition(
                "Gate advancement requires explicit confirmation attributed "
                "to diego. Refusing an anonymous/automated confirmation."
            )
        return GateState(gate=new_gate, opened_at=datetime.now(timezone.utc).isoformat(), opened_by=confirmed_by)


@dataclass
class AccountState:
    """Section 2 tracking. Backtest/paper/shadow modes still update this
    from simulated fills, so the limits engine is exercised identically
    regardless of gate — the only thing that changes at live gates is
    whether `execution_guard` allows a real order downstream of PM.
    """

    equity: float = 0.0
    daily_pnl: float = 0.0
    daily_pnl_date: str = field(default_factory=lambda: date.today().isoformat())
    open_positions: int = 0
    consecutive_losses: int = 0
    circuit_breaker_tripped: bool = False
    trading_halted_today: bool = False

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AccountState":
        path = path or (Paths().data_dir / "account_state.json")
        if not path.exists():
            return cls()
        return cls(**json.loads(path.read_text()))

    def save(self, path: Optional[Path] = None) -> None:
        path = path or (Paths().data_dir / "account_state.json")
        path.write_text(json.dumps(asdict(self), indent=2))

    def roll_day_if_needed(self) -> "AccountState":
        """Daily reset (called by the cron entrypoint before each chain
        run): clears daily P&L and the daily halt. Deliberately does NOT
        clear circuit_breaker_tripped — Section 2 requires that pause and
        notify, don't auto-resume, and a new calendar day is not a
        resume decision.
        """
        today = date.today().isoformat()
        if self.daily_pnl_date != today:
            self.daily_pnl = 0.0
            self.daily_pnl_date = today
            self.trading_halted_today = False
        return self
