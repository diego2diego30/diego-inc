"""Hermes — orchestrator/supervisor for the Diego, Inc. trading instance.

See docs/execution-plan.md for the governing spec. This package implements
Sections 1-4: the six-role chain, hard limits, gating, and reasoning logs.
"""

__all__ = ["config", "state", "limits", "execution_guard", "logging_utils", "orchestrator", "telegram_bridge"]
