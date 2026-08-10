"""Command-line entrypoints. This is what cron, systemd, and Diego (for the
human-only gate/circuit-breaker actions) actually invoke.

    python -m hermes.cli run-chain --universe "SPY,QQQ"
    python -m hermes.cli open-gate --gate paper --confirmed-by diego
    python -m hermes.cli resume-circuit-breaker --confirmed-by diego
    python -m hermes.cli cost-report
    python -m hermes.cli telegram-daemon
"""
from __future__ import annotations

import argparse
import sys

from hermes import chat
from hermes.config import LimitsConfig, Paths
from hermes.cost import CostLedger
from hermes.limits import LimitsEngine
from hermes.orchestrator import run_chain
from hermes.state import AccountState, GateState
from hermes.telegram_bridge import TelegramBridge, TelegramConfig

# Words that trigger an on-demand cost report over Telegram (Section 5:
# Diego asked to be able to check projected usage cost on demand, not just
# see it in cron output). Matched case-insensitively against the whole
# message so "cost", "Cost?", "/cost" all work.
COST_REPORT_TRIGGERS = {"cost", "/cost", "cost report", "costs", "usage", "spend"}

# On-demand check that HTML parse_mode is rendering as expected -- see the
# same trigger/message in the Quinta55 instance's hermes/cli.py.
HTML_TEST_TRIGGERS = {"html test", "/htmltest", "htmltest"}

HTML_DEMO_MESSAGE = (
    "<b>HTML formatting test</b> ([trading] bot)\n\n"
    "<b>Bold</b> / <strong>Bold</strong>\n"
    "<i>Italic</i> / <em>Italic</em>\n"
    "<u>Underline</u> / <ins>Underline</ins>\n"
    "<s>Strikethrough</s> / <strike>Strikethrough</strike> / <del>Strikethrough</del>\n"
    "<b><i>Bold italic</i></b>\n"
    "<span class=\"tg-spoiler\">Spoiler (tap to reveal)</span>\n"
    "<a href=\"https://telegram.org\">Inline link</a>\n"
    "<code>inline fixed-width code</code>\n\n"
    "<pre>Pre-formatted block\nno syntax highlighting</pre>\n\n"
    "<pre><code class=\"language-python\">def hello():\n    return \"hi\"</code></pre>\n\n"
    "<blockquote>Regular blockquote</blockquote>\n\n"
    "<blockquote expandable>Expandable blockquote -- tap to expand/collapse.</blockquote>"
)


def cmd_run_chain(args: argparse.Namespace) -> int:
    result = run_chain(instrument_universe=args.universe)
    try:
        bridge = TelegramBridge(config=TelegramConfig())
        bridge.send_chain_summary(result)
    except Exception as exc:  # noqa: BLE001
        # Telegram being unreachable must never look like the chain
        # itself failed -- the run already completed and logged.
        print(f"warning: chain completed but Telegram notify failed: {exc}", file=sys.stderr)
    print(result)
    return 0


def cmd_open_gate(args: argparse.Namespace) -> int:
    # This is the one and only place in the codebase that calls
    # GateState.advance_to -- deliberately gated behind requiring the
    # human to type --confirmed-by diego themselves on the VPS.
    state = GateState.load()
    new_state = state.advance_to(args.gate, confirmed_by=args.confirmed_by)
    new_state.save()
    print(f"Gate advanced: {state.gate} -> {new_state.gate} (confirmed by {args.confirmed_by})")
    return 0


def cmd_resume_circuit_breaker(args: argparse.Namespace) -> int:
    account = AccountState.load()
    engine = LimitsEngine(LimitsConfig(), account)
    engine.resume_after_circuit_breaker(confirmed_by=args.confirmed_by)
    account.save()
    print(f"Circuit breaker cleared (confirmed by {args.confirmed_by})")
    return 0


def cmd_cost_report(args: argparse.Namespace) -> int:
    report = CostLedger().report()
    print(report.as_text())
    return 0


BOT_COMMANDS = [
    ("cost", "Show this month's spend report"),
    ("htmltest", "Send an HTML formatting demo"),
]


def cmd_telegram_daemon(args: argparse.Namespace) -> int:
    bridge = TelegramBridge(config=TelegramConfig())
    try:
        bridge.set_commands(BOT_COMMANDS)
    except Exception as exc:  # noqa: BLE001 - cosmetic; must not block the daemon starting
        print(f"warning: setting bot command menu failed: {exc}", file=sys.stderr)

    def handle(text: str) -> None:
        print(f"received from Diego: {text}")

        if text.strip().lower() in COST_REPORT_TRIGGERS:
            report = CostLedger().report()
            try:
                bridge.send_status(report.as_text())
            except Exception as exc:  # noqa: BLE001 - a failed reply must not crash the daemon
                print(f"warning: cost report reply failed: {exc}", file=sys.stderr)
            return

        if text.strip().lower() in HTML_TEST_TRIGGERS:
            try:
                bridge.send_status(HTML_DEMO_MESSAGE, escape=False)
            except Exception as exc:  # noqa: BLE001 - a failed reply must not crash the daemon
                print(f"warning: html test reply failed: {exc}", file=sys.stderr)
            return

        # Confirm/reject wiring against a pending live-execution proposal
        # gets added here once Section 3 Gate 4 is opened and a real
        # broker integration exists (see hermes/execution_guard.py).

        # Anything else: conversational fallback (hermes/chat.py). No tools,
        # billed through the same CostLedger as the chain roles -- see that
        # module's docstring. A failed reply must not crash the daemon, same
        # as the cost-report path above.
        try:
            reply = chat.reply_to_message(text, paths=Paths())
            bridge.send_status(reply)
        except Exception as exc:  # noqa: BLE001 - a failed reply must not crash the daemon
            print(f"warning: chat reply failed: {exc}", file=sys.stderr)

    bridge.poll_for_replies(handle)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run-chain", help="Run one Analyst->...->PM cycle")
    p_run.add_argument("--universe", required=True, help="e.g. 'SPY,QQQ' or a watchlist name")
    p_run.set_defaults(func=cmd_run_chain)

    p_gate = sub.add_parser("open-gate", help="Advance to the next gate (Section 3) -- human-only")
    p_gate.add_argument("--gate", required=True, choices=["backtest", "paper", "shadow", "live_small", "live_scaled"])
    p_gate.add_argument("--confirmed-by", required=True, help="Must be 'diego'")
    p_gate.set_defaults(func=cmd_open_gate)

    p_resume = sub.add_parser("resume-circuit-breaker", help="Manually clear a tripped circuit breaker -- human-only")
    p_resume.add_argument("--confirmed-by", required=True, help="Must be 'diego'")
    p_resume.set_defaults(func=cmd_resume_circuit_breaker)

    p_cost = sub.add_parser("cost-report", help="Print month-to-date spend, projection, and cap status")
    p_cost.set_defaults(func=cmd_cost_report)

    p_tg = sub.add_parser("telegram-daemon", help="Long-running process that listens for Diego's replies")
    p_tg.set_defaults(func=cmd_telegram_daemon)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
