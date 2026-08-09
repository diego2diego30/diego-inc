"""Coverage for hermes/chat.py: session persistence and the budget guard
that keeps conversational replies inside the same spend cap as chain runs
(see hermes/cost.py) rather than opening a second, uncapped path. Doesn't
mock the `claude` subprocess itself -- these test the logic around it.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone

from hermes import chat
from hermes.config import Paths
from hermes.cost import BudgetExceeded


class TestChatSession:
    def test_round_trips_a_session_id(self):
        session = chat.ChatSession(paths=Paths())
        session.save("sess-123")
        assert session.load() == "sess-123"

    def test_returns_none_when_nothing_saved_yet(self):
        assert chat.ChatSession(paths=Paths()).load() is None

    def test_resets_after_the_idle_window(self):
        session = chat.ChatSession(paths=Paths())
        # Backdate the saved timestamp past SESSION_IDLE_RESET_SECONDS
        # directly, rather than sleeping in a test for six hours.
        stale_at = datetime.now(timezone.utc) - timedelta(
            seconds=chat.SESSION_IDLE_RESET_SECONDS + 1
        )
        session._path.write_text(json.dumps({
            "session_id": "sess-stale",
            "last_message_at": stale_at.isoformat(),
        }))
        assert session.load() is None

    def test_survives_a_corrupt_state_file(self):
        session = chat.ChatSession(paths=Paths())
        session._path.write_text("not json")
        assert session.load() is None


class TestReplyToMessageBudgetGuard:
    def test_returns_fallback_and_never_calls_claude_when_budget_exceeded(self, monkeypatch):
        def _raise(*_args, **_kwargs):
            raise BudgetExceeded("monthly cap reached")

        monkeypatch.setattr("hermes.cost.CostLedger.assert_within_budget", _raise)

        calls = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))

        reply = chat.reply_to_message("hey what's up", paths=Paths())

        assert reply == chat.FALLBACK_BUDGET_EXCEEDED
        assert calls == []  # the whole point of the guard: no subprocess, no spend
