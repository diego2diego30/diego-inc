"""Telegram bridge — status pushes and confirm/reject replies for the
trading instance's Hermes. Section 4: "Telegram bot wired to Hermes for
status pushes and confirm/reject replies." Section 6: keep this bot/thread
separate from the Quinta55 instance's bot so a glance at your phone tells
you which domain a message is about.

Uses the raw Bot API over HTTPS (no extra framework dependency) — see
requirements.txt. Token/chat id come from TelegramConfig (env-only, never
hard-coded — see hermes/config.py).
"""
from __future__ import annotations

import html
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from hermes.config import TelegramConfig

API_BASE = "https://api.telegram.org/bot{token}"


@dataclass
class TelegramBridge:
    config: TelegramConfig

    def _url(self, method: str) -> str:
        return f"{API_BASE.format(token=self.config.bot_token)}/{method}"

    def send_status(self, text: str, *, escape: bool = True) -> None:
        """escape=False is only for trusted, hard-coded HTML built in this
        codebase (e.g. the html-test demo in cli.py) -- never pass through
        text that originated from Telegram, an LLM, or any other untrusted
        source with escape=False.
        """
        resp = requests.post(
            self._url("sendMessage"),
            json={
                "chat_id": self.config.chat_id,
                "text": html.escape(text) if escape else text,
                "parse_mode": "HTML",
            },
            timeout=15,
        )
        resp.raise_for_status()

    def send_rich_status(self, rich_html: str) -> None:
        """Sends a structured rich message via sendRichMessage -- a
        separate, much larger Bot API surface than send_status's plain
        sendMessage/parse_mode=HTML (tables, headings, lists, blockquotes
        with <cite>, collapsible <details>, etc.; see
        https://core.telegram.org/bots/api#rich-message-formatting-options).
        rich_html must be trusted, pre-built markup -- manually escape any
        dynamic/untrusted content embedded in it (e.g. via html.escape())
        before calling this, the same rule as send_status(escape=False).
        """
        resp = requests.post(
            self._url("sendRichMessage"),
            json={
                "chat_id": self.config.chat_id,
                "rich_message": {"html": rich_html},
            },
            timeout=15,
        )
        resp.raise_for_status()

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        """Registers Telegram's native "/" autocomplete menu. Only ever
        list commands `handle()` actually acts on (see cli.py) -- a menu
        entry for something that doesn't do anything from Telegram would
        be a UI lie, not a convenience.
        """
        resp = requests.post(
            self._url("setMyCommands"),
            json={"commands": [{"command": c, "description": d} for c, d in commands]},
            timeout=15,
        )
        resp.raise_for_status()

    def send_chain_summary(self, chain_result: dict) -> None:
        gate = chain_result["gate"]
        approved = chain_result["decision_approved"]
        live = chain_result["live_authorized"]
        lines = [
            f"[trading] cycle complete — gate: {gate}",
            f"Decision approved: {approved}",
            f"Live execution authorized: {live}",
            "",
            chain_result.get("pm_summary", "")[:1500],
        ]
        self.send_status("\n".join(lines))

    def poll_for_replies(
        self,
        on_message: Callable[[str], None],
        stop_after_seconds: Optional[int] = None,
    ) -> None:
        """Long-poll getUpdates for Diego's confirm/reject replies. Run as
        its own supervised process (systemd), not inside the cron-driven
        chain run, so a reply can arrive at any time independent of the
        screener cadence.
        """
        offset = None
        start = time.monotonic()
        while stop_after_seconds is None or (time.monotonic() - start) < stop_after_seconds:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            resp = requests.get(self._url("getUpdates"), params=params, timeout=40)
            resp.raise_for_status()
            for update in resp.json().get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message", {})
                if str(message.get("chat", {}).get("id")) != str(self.config.chat_id):
                    continue  # ignore anything not from Diego's configured chat
                text = message.get("text")
                if text:
                    # The handler (hermes/cli.py) already guards its own
                    # risky calls, but this is the backstop: an uncaught
                    # exception here must not kill the long-poll loop --
                    # that would silence the bot until systemd notices and
                    # restarts it, losing every message in between.
                    try:
                        on_message(text)
                    except Exception as exc:  # noqa: BLE001
                        print(f"warning: on_message handler raised: {exc}", file=sys.stderr)
