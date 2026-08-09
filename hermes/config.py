"""Environment-driven configuration. No secrets or real values are
hard-coded here — everything comes from the environment (see
`deploy/.env.example` for the full list) so this file is safe to commit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class MissingConfigError(RuntimeError):
    """Raised when required configuration is absent, instead of silently
    falling back to a placeholder that could be mistaken for a real value.
    """


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingConfigError(
            f"{name} is not set. See deploy/.env.example — copy it to "
            f"deploy/.env on the VPS and fill in real values. Refusing to "
            f"start with a fabricated placeholder."
        )
    return value


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class LimitsConfig:
    """Section 2 hard limits. Defaults here are conservative placeholders
    for backtest/paper use — Diego should set real values via env vars
    before any gate advances past Backtest.
    """

    daily_max_loss_pct: float = field(default_factory=lambda: _float("DAILY_MAX_LOSS_PCT", 2.0))
    max_position_size_pct: float = field(default_factory=lambda: _float("MAX_POSITION_SIZE_PCT", 5.0))
    max_open_positions: int = field(default_factory=lambda: _int("MAX_OPEN_POSITIONS", 5))
    circuit_breaker_consecutive_losses: int = field(
        default_factory=lambda: _int("CIRCUIT_BREAKER_CONSECUTIVE_LOSSES", 3)
    )


@dataclass(frozen=True)
class Paths:
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def trading_root(self) -> Path:
        return self.repo_root / "trading"

    @property
    def roles_dir(self) -> Path:
        return self.trading_root / "roles"

    @property
    def logs_dir(self) -> Path:
        return self.trading_root / "logs"

    @property
    def memory_dir(self) -> Path:
        return self.trading_root / "memory"

    @property
    def claude_md(self) -> Path:
        return self.trading_root / "CLAUDE.md"

    @property
    def data_dir(self) -> Path:
        # Hermes's own runtime state, deliberately outside trading/ — see
        # execution-plan.md Section A: "Hermes maintains its own
        # conversation and session state within its container's data
        # volume, independent of the CLAUDE.md/MEMORY.md files."
        d = Path(os.environ.get("HERMES_DATA_DIR", self.repo_root / "data"))
        d.mkdir(parents=True, exist_ok=True)
        return d


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = field(default_factory=lambda: _require("TELEGRAM_BOT_TOKEN"))
    chat_id: str = field(default_factory=lambda: _require("TELEGRAM_CHAT_ID"))


# Claude model per role — Section 5 cost control: mix tiers by role, not
# one model for all six. Data-pull/low-stakes roles on Haiku, decision
# roles on Sonnet. Overridable per-role via env for real usage tuning.
DEFAULT_MODEL_BY_ROLE = {
    "analyst": os.environ.get("MODEL_ANALYST", "claude-haiku-4-5-20251001"),
    "bull": os.environ.get("MODEL_BULL", "claude-haiku-4-5-20251001"),
    "bear": os.environ.get("MODEL_BEAR", "claude-haiku-4-5-20251001"),
    "trader": os.environ.get("MODEL_TRADER", "claude-sonnet-5"),
    "risk": os.environ.get("MODEL_RISK", "claude-sonnet-5"),
    "pm": os.environ.get("MODEL_PM", "claude-sonnet-5"),
    "chat": os.environ.get("MODEL_CHAT", "claude-haiku-4-5-20251001"),
}

ROLE_CHAIN = ["analyst", "bull", "bear", "trader", "risk", "pm"]

# Section 3: gates are sequential, no skipping, and only Diego opens the
# next one. This is the closed set of valid values — nothing in this
# codebase writes a value outside this list.
GATES = ["backtest", "paper", "shadow", "live_small", "live_scaled"]
