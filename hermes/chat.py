"""Conversational fallback for the Telegram daemon. Anything that doesn't
match COST_REPORT_TRIGGERS falls through to here (see hermes/cli.py).

Deliberately separate from orchestrator.py: this is a single call, not a
six-role chain, needs session resumption for multi-turn conversation, and
has no RunLock/multi-role billing loop to reuse.

Zero tool access (--allowedTools "") -- the conversational path can never
read/write a file or take an action. Only the trigger-word command path in
cli.py is privileged. It still gets the same static CLAUDE.md context every
`claude -p` call auto-loads from cwd (trading/CLAUDE.md + roles/chat/CLAUDE.md).
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hermes.config import DEFAULT_MODEL_BY_ROLE, Paths
from hermes.cost import BudgetExceeded, CostLedger, cost_from_claude_response

# Session resets after this long of inactivity, so a stale days-old
# conversation doesn't silently keep growing context (and cost) forever.
SESSION_IDLE_RESET_SECONDS = 6 * 3600

# Telegram's hard per-message limit is 4096 chars; stay well under it.
MAX_REPLY_CHARS = 3500

FALLBACK_BUDGET_EXCEEDED = (
    "Monthly budget cap reached -- can't chat right now, try `cost` for details."
)


class ChatError(RuntimeError):
    pass


@dataclass
class ChatSession:
    """Persists the last `claude -p` session id across Telegram messages, so
    replies can use --resume for real conversational memory instead of
    treating each message in isolation.
    """

    paths: Paths

    @property
    def _path(self) -> Path:
        return self.paths.data_dir / "chat_session.json"

    def load(self) -> Optional[str]:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
            last = datetime.fromisoformat(data["last_message_at"])
            age = (datetime.now(timezone.utc) - last).total_seconds()
        except (json.JSONDecodeError, KeyError, ValueError):
            return None  # unreadable state -- start fresh rather than guess
        if age > SESSION_IDLE_RESET_SECONDS:
            return None
        return data.get("session_id") or None

    def save(self, session_id: str) -> None:
        self._path.write_text(json.dumps({
            "session_id": session_id,
            "last_message_at": datetime.now(timezone.utc).isoformat(),
        }))


def reply_to_message(text: str, paths: Optional[Paths] = None) -> str:
    """Generate a conversational reply to an incoming Telegram message that
    didn't match any command trigger. Billed through the same CostLedger the
    chain roles use (cost_from_claude_response with no run_id, so it counts
    toward MONTHLY_USD_CAP but not the chain-specific MAX_RUNS_PER_DAY
    counter, which is about cron/manual chain triggers, not chat) -- no
    separate, uncapped spend path. assert_run_within_cap isn't called here:
    that guard exists to cut a multi-role chain off mid-run, and a single
    haiku conversational turn is never going to approach PER_RUN_USD_CAP.
    """
    paths = paths or Paths()
    ledger = CostLedger(paths=paths)

    try:
        ledger.assert_within_budget()
    except BudgetExceeded:
        return FALLBACK_BUDGET_EXCEEDED

    session = ChatSession(paths=paths)
    session_id = session.load()

    model = DEFAULT_MODEL_BY_ROLE["chat"]
    role_dir = paths.roles_dir / "chat"
    if not role_dir.exists():
        raise ChatError(f"No chat role directory at {role_dir}")

    cmd = [
        "claude", "-p", text,
        "--model", model,
        "--allowedTools", "",
        "--output-format", "json",
    ]
    if session_id:
        cmd += ["--resume", session_id]

    proc = subprocess.run(cmd, cwd=str(role_dir), capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise ChatError(f"chat reply failed (exit {proc.returncode}): {proc.stderr[:2000]}")

    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raw = {"result": proc.stdout}

    reply = raw.get("result") or proc.stdout or "(no reply)"

    usage = cost_from_claude_response("chat", model, raw)
    ledger.record(usage)

    new_session_id = raw.get("session_id")
    if new_session_id:
        session.save(new_session_id)

    return reply[:MAX_REPLY_CHARS]
