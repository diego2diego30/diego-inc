# Execution Plan — Multi-Agent Trading & Diego, Inc. System

Owner: Diego Ortuondo-Leme
Drafted: 07 Aug 2026 (3 days of leave remaining — leave ends 10 Aug)

---

## A. Architecture Summary

**Poke**
Poke is a third-party, cloud-hosted conversational assistant operated by The Interaction Company, accessible via iMessage, SMS, Telegram, and WhatsApp. Its scope is restricted to the personal and administrative domain, including calendar management, reminders, smart-home control, and general query handling. Poke operates on infrastructure external to Diego's own systems and does not hold financial credentials, trading account access, or business-system access. Interaction with the other two systems is limited to non-sensitive, informational content — for example, a calendar reminder that references the status of another system. No credentials or execution authority are shared between Poke and either Hermes instance.
- **Context/memory storage:** Stored on Poke's/Interaction Company's own servers, external to Diego's infrastructure. No content originating from the Trading or Quinta55 instances is stored within Poke, and no content originating from Poke is to be replicated into either instance.

**Diego, Inc.**
Diego, Inc. is a self-hosted, multi-agent orchestration framework deployed on Diego's existing Cloudflare VPS. Its core components are as follows:
- **Hermes** — the orchestrator and supervisor process, responsible for the conversational interface (via Telegram) and for coordinating subordinate agents.
- **Claude Code** — headless execution agents (invoked via `claude -p`), each scoped to a single role through its own CLAUDE.md file and defined tool permissions.
- **MCP servers** — integrations providing market data, task-list access, and, in a later phase, account APIs.

The trading system constitutes the primary Diego, Inc. deployment under this framework. It consists of six role-specialized agents — Analyst, Bull researcher, Bear researcher, Trader, Risk manager, and Portfolio manager — operating as a periodic screener rather than an intraday loop (see Section 1). Governance is enforced through hard-coded risk limits, a staged gate progression from backtest to live capital (Sections 2–3), and per-decision reasoning logs. Credentials associated with this instance are scoped exclusively to trading accounts.
- **Context/memory storage:** Stored locally on the VPS, under `/opt/ecosystem/trading/`:
  - `/opt/ecosystem/trading/CLAUDE.md` — standing instructions applicable across the instance
  - `/opt/ecosystem/trading/roles/<role-name>/CLAUDE.md` — one file per role (analyst, bull, bear, trader, risk, pm), defining that agent's specific context and permissions
  - `/opt/ecosystem/trading/MEMORY.md` — the auto-memory index (Claude Code's built-in auto-memory system, capped at 200 lines or 25KB on load)
  - `/opt/ecosystem/trading/memory/` — auto-memory topic files referenced by the index
  - `/opt/ecosystem/trading/logs/` — per-decision reasoning logs, per Section 4
  - Hermes maintains its own conversation and session state within its container's data volume, independent of the CLAUDE.md/MEMORY.md files listed above. Hermes reads those files as context for each `claude -p` invocation, but its dialogue history with Diego is stored separately.

**Quinta55**
Quinta55 is a business vertical operating under the Diego, Inc. umbrella, implemented as a second, independently deployed Hermes instance. Its purpose is to provide AI-agentic operational support for Quinta55 Reserve, the family coffee business. It is deployed as a separate Docker container on the same VPS as the trading instance, with its own Hermes process, its own CLAUDE.md/MEMORY.md files, and its own credentials. This isolation is deliberate and is intended to prevent a fault or compromise within the trading domain from affecting business operations, and vice versa.
- **Context/memory storage:** Stored locally on the VPS, under `/opt/ecosystem/quinta55/`, mirroring the trading instance's directory structure (`CLAUDE.md`, `roles/`, `MEMORY.md`, `memory/`, `logs/`) with no overlap in content. No trading rules, account state, or credentials are present anywhere under this path, and no file under `/opt/ecosystem/trading/` is accessible from this container.

**System relationship:**

```
                          Diego
                            |
              ------------------------------
              |                            |
            Poke                    Cloudflare VPS
      (personal admin,                     |
       3rd-party hosted,      ------------------------------
      memory on Poke's         |                            |
        own servers)    Hermes: Trading            Hermes: Quinta55
                     (6-role agent chain,        (business ops agents,
                      periodic screener)          Diego Inc. context)
                               |                            |
                      Claude Code (headless,        Claude Code (headless,
                       claude -p, cron)              claude -p, cron)
```

**On-VPS storage layout:**

```
/opt/ecosystem/
├── trading/
│   ├── CLAUDE.md          (instance-wide standing instructions)
│   ├── MEMORY.md           (auto-memory index)
│   ├── memory/             (auto-memory topic files)
│   ├── roles/
│   │   ├── analyst/CLAUDE.md
│   │   ├── bull/CLAUDE.md
│   │   ├── bear/CLAUDE.md
│   │   ├── trader/CLAUDE.md
│   │   ├── risk/CLAUDE.md
│   │   └── pm/CLAUDE.md
│   └── logs/                (per-decision reasoning logs)
└── quinta55/
    ├── CLAUDE.md
    ├── MEMORY.md
    ├── memory/
    ├── roles/               (business-workflow roles, defined per Section 7)
    └── logs/
```

No file under `trading/` is readable from the `quinta55/` container or process, and no file under `quinta55/` is readable from `trading/`.

---

## B. Execution Instructions (for Claude Code)

When this document is provided to Claude Code as project context, treat it as the authoritative specification for bootstrapping this ecosystem, and follow this sequence:

1. **Confirm scope before acting.** This document describes two independent deployments — the Trading instance and the Quinta55 instance. Do not begin implementation until Diego specifies which instance is in scope for the current session.
2. **No live-execution code path** (real trades, real financial transactions, real business-system writes) under any circumstances until Section 2's hard limits are implemented and tested, and Section 3's gate 4 is explicitly reached and confirmed by Diego. Proposal-only and paper/shadow modes are the default until that confirmation.
3. **Scaffold in this order, using the paths defined in Section A's storage layout:** (a) `/opt/ecosystem/trading/` and `/opt/ecosystem/quinta55/` directory structure, separated from the first commit; (b) role-scoped `CLAUDE.md` files under each instance's `roles/` directory per Sections 1 and 6; (c) hard-limit enforcement code per Section 2; (d) MCP server integrations per Section 4; (e) Docker/systemd/cron wiring per Section 4; (f) Telegram bridge. Do not place any file under the wrong instance's directory, and do not create a shared `memory/` or `CLAUDE.md` that both instances read from.
4. **Request missing configuration explicitly** — API keys, broker/exchange selection, account credentials, MCP endpoints — rather than assuming or fabricating placeholder values that could be mistaken for real ones.
5. **Keep the two instances separate from the first commit.** Do not scaffold Trading and Quinta55 as a shared codebase "to be split later" — separate directories, separate containers, separate credential stores from the start.
6. **Every change touching Section 2's hard limits requires a corresponding test** before being considered complete.
7. **Log reasoning per Section 4 from the first working version**, not as a later add-on.
8. **At each phase boundary in Section 7 (Timeline), stop and summarize** what was completed against this document before proceeding to the next phase — do not chain multiple phases together in one unattended run.

---

## 0. Governing architecture (recap)

Three segregated personas, no shared execution authority between them:

- **Poke** — personal/admin only. Calendar, reminders, day-to-day texting. Never touches finance or business context.
- **Hermes — Trading instance (self-hosted, on your Cloudflare VPS)** — supervisor for the trading system only. Talks to you via Telegram. Spawns and monitors the headless Claude Code trading agents. Own credentials, own memory files.
- **Hermes — Quinta55/Diego, Inc. instance (self-hosted, same VPS, separate container)** — supervisor for the business side: Quinta55 Reserve ops and Diego, Inc. work. Own credentials, own memory files, own Telegram bot/thread if you want separate notifications.

Same reasoning as the Poke/Hermes split applies *between* the two Hermes instances: your trading account and your mom's business shouldn't sit behind the same credentials or the same agent memory, even though both are "Hermes" and both live on hardware you control. Running both on one VPS is fine — it's just more containers on infrastructure you've already provisioned — but keep them as genuinely separate processes with separate memory/context, not one instance juggling two domains.

Everything below (Sections 1–3, 5) describes the **trading instance**. Section 6 covers how Quinta55's own context should be structured in parallel.

---

## 1. Agent roles — periodic screener, not a day-trading loop

**Model change:** this runs as a daily/weekly periodic screener with longer holding periods, not an intraday day-trading loop. The evidence is one-sided here — studies spanning Taiwan, Brazil, and FINRA disclosures consistently show 70–97% of day traders lose money, with only ~1–3% consistently profitable over 3+ years, largely because transaction costs, short-term capital gains taxes, and slippage compound with every trade. Frequency doesn't buy you more edge; it mostly buys you more cost. A periodic screen-and-hold model is both cheaper to run (Section 5) and closer to what the evidence actually supports.

Each role is a **separate headless Claude Code agent**, invoked via `claude -p`, with its own scoped CLAUDE.md and its own `--allowedTools`. No single agent sees or does everything — this is what let other builders' review panels catch bugs a generalist agent missed.

| Role | Job | Reads | Can do |
|---|---|---|---|
| **Analyst** | Pull market state — price, volume, technicals, relevant news, on a daily/weekly cadence | Market data MCP | Read-only |
| **Bull researcher** | Build the strongest case *for* a position | Analyst's output | Read-only |
| **Bear researcher** | Build the strongest case *against* | Analyst's output | Read-only |
| **Trader** | Weigh bull/bear debate, propose a specific position + size, sized for a longer hold | Both researchers' output | Read-only, proposes only |
| **Risk manager** | Check proposal against hard limits (below). Can veto or shrink size | Trader's proposal, account state | Read-only, can block |
| **Portfolio manager** | Final call — approve, reject, or escalate to you | Everything above | Approve/reject only |

**On social sentiment (X trends) as a signal:** treat it as one weak input into the Analyst's read, never as a standalone trigger. It's consistently the noisiest, most lagging signal in serious builds — by the time a trend is visible on X the move it reflects has often already happened, and social-media-driven spikes are a common pump-and-dump pattern. If you wire in an X/social feed, have the Analyst flag it as low-confidence context for the Bull/Bear debate, not something the Trader acts on directly.

Hermes is the orchestrator that runs this chain on a schedule and holds the conversation with you — it is not itself one of the six roles.

---

## 2. Hard limits — coded, not prompted

These live in enforcement code the agents call, not just as CLAUDE.md instructions an agent could reason around:

- [ ] Daily max-loss limit (hard stop, trading halts for the day if hit)
- [ ] Max position size as % of account
- [ ] Max number of open positions at once
- [ ] Circuit breaker: N consecutive losing trades → pause and notify, don't auto-resume

Until every box above is implemented in code and tested, **no agent gets live execution permission** — proposal/paper-trade only.

---

## 3. The gate before real money

Sequential, no skipping:

1. **Backtest** — strategy against historical data
2. **Paper trade** — live data, simulated fills, for a defined stretch. With a periodic screener and longer holds, this window should cover enough full hold-cycles to be meaningful, not just calendar time — recommend a minimum of 4–6 weeks, but extend it if your typical hold period means that only captures a handful of complete trades
3. **Shadow mode** — live data, real-time proposals logged, still no execution, running *in parallel* with paper trading to compare
4. **Live, small size** — real capital, capped at a size you'd be fully fine losing, hard limits from Section 2 active
5. **Live, scaled** — only after live-small has run cleanly through at least one full drawdown

You decide when each gate opens. Hermes reports readiness; it does not self-promote through the gates.

---

## 4. Infrastructure

Reuses what you already run for ARES-WERX — no new platform to learn:

- Same Cloudflare VPS, new Docker container(s) for this system
- `systemd` or `pm2` to keep the Hermes process alive across reboots/crashes
- Cron triggers `claude -p` runs for each scheduled agent check (market hours cadence for Analyst → chain; daily for Diego Inc./todo sweep)
- MCP servers for: market data feed, your Google Sheet/Obsidian task list, and (later) the trading account API — read-only scopes wherever possible
- Every run logs `reasoning` + decision to a file — not just the final action, so a bad trade is traceable back through the chain afterward
- Telegram bot wired to Hermes for status pushes and confirm/reject replies

---

## 5. Compute billing & cost control

Headless usage (`claude -p`, everything this plan runs on a schedule) does **not** draw from your interactive Claude Pro subscription. As of June 2026, Anthropic separated the two: interactive Claude Code (typing in a terminal, Cowork) still uses your normal Pro plan limits. Headless/scripted calls — which is all six agent roles, running on cron — draw from a **separate monthly Agent SDK credit**: $20/month on Pro, billed at standard API rates, no rollover. Once that's spent, headless calls stop unless you've opted into pay-as-you-go overage with a spend cap.

**Cost-control rules for this system:**

- [ ] **Mix model tiers by role, not one model for all six.** Analyst (data pull, low-stakes) runs on Haiku. Bull/Bear researchers can also run on Haiku or Sonnet. Trader, Risk manager, and Portfolio manager — the roles that actually decide — run on Sonnet (reserve Opus for periodic deeper review, not every cycle).
- [ ] **Default to daily/weekly cadence, not intraday polling.** This isn't just a cost optimization — Section 1's evidence review is the actual reason: intraday day-trading frequency doesn't correlate with better returns for individuals, it mostly correlates with more fees, more taxes, and worse outcomes. The periodic-screener cadence is the recommended default, not a fallback.
- [ ] **Enable prompt caching** for anything reused across calls — your CLAUDE.md context, market data schemas, the standing role instructions. Cached input tokens cost a fraction of fresh ones, and this system re-sends the same context on every cycle.
- [ ] **Set a hard monthly spend cap** on API/usage-credit overflow, same discipline as the trading hard-limits in Section 2. A bug in the cron loop should hit a billing ceiling, not an unbounded bill.
- [ ] **Re-check actual usage after week one.** Any estimate below is a planning number, not a bill — pull real token counts from your first week of runs and recalibrate before assuming the number holds.

**Rough monthly estimate (assumptions stated — recalibrate after real logs):**

| Cadence | Chain runs/month | Total agent calls | Estimated cost/mo |
|---|---|---|---|
| **Recommended — daily screen, weekly deep review** | ~25–30 | ~150–180 | **~$5–15** |
| Not recommended — intraday polling (every 15–30 min) | ~500+ | ~3,000+ | **~$100–250**, plus the return drag from Section 1 |
| Diego Inc./todo sweep (daily, separate from trading) | 30 | 30 | **~$2–5** |

Infrastructure itself adds effectively $0 marginal cost — you're already paying for the Cloudflare VPS for ARES-WERX; this is one more Docker container on hardware you've already provisioned.

**Bottom line:** the periodic-screener model comfortably fits inside the $20/month Agent SDK credit, with room to spare. It's a strictly better default on both cost and the evidence in Section 1 — there's no longer a real tradeoff pushing toward the intraday row.

---

## 6. Memory & context

**Trading instance:**
- `MEMORY.md` — trading rules, hard limits, current gate status, account state. No personal-life content, no Quinta55/Diego Inc. content.
- Auto memory: allow it for pattern-learning (e.g., which setups the Analyst flags well), but **review additions periodically** rather than trusting silent accumulation — this matters more here than in a coding-only agent, since a wrong "learned" assumption compounds across scheduled runs.

**Quinta55/Diego, Inc. instance — separate container, separate Hermes process:**
- Its own `CLAUDE.md`/context — business goals, design ethos, career-direction notes, Quinta55 operational details. No trading credentials, no account state, no trading strategy details.
- Its own credentials for whatever Quinta55/Diego Inc. tools it touches (accounting, ops, whatever the business needs) — never shared with the trading instance's credential set.
- Runs on the same VPS as the trading instance, but as a genuinely separate Docker container/process — not a second "mode" of the same Hermes instance.

The two instances can both notify you via Telegram, but keep them as separate bots/threads if possible so a glance at your phone tells you which domain a message is about.

---

## 7. Timeline, matched to your actual schedule

**Now → 10 Aug (remaining leave):**
- [ ] Stand up Hermes on the VPS, Telegram bridge working
- [ ] Write the six role-scoped CLAUDE.md files
- [ ] Implement hard limits (Section 2) in code — this is the one piece that must exist before anything else proceeds
- [ ] Wire the Analyst → Bull/Bear → Trader → Risk → PM chain, proposal-only, no execution

**Once back at USNA (weekday-constrained):**
- Backtest + paper trading run continuously via cron regardless of your availability — this is exactly the kind of work suited to leave-period setup, school-year unattended running
- Weekend blocks: review logs, refine the Risk manager's limits, adjust strategy based on paper-trading results
- Do not open the live-small gate (Section 3, step 4) during a stretch you can't actively monitor for the first few sessions

**Next leave period:**
- Evaluate paper-trading + shadow-mode results
- If clean, open live-small gate
- Stand up the second Hermes instance for Quinta55/Diego, Inc. — its own container, own credentials, own memory — and apply the same role-separation pattern (research/build/review roles rather than bull/bear/trader) to business workflows

---

## 8. What "done" looks like for v1

Not "the bot is profitable." It's: hard limits enforced in code and tested, six roles running on schedule producing logged/traceable decisions, 4–6 weeks of clean paper trading, and a Telegram confirm step you actually trust before anything touches real capital.
