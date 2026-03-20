---
name: agent-observability
description: Agent observability principles for ollim-bot. Apply when building features that affect agent behavior, adding tools, or auditing whether behavior is traceable and debuggable. Covers the three observability layers (Claude Code OTel, Agent SDK hooks, application state).
---

# Agent Observability

When behavior is wrong, start with "what did the agent actually see?" — not "how should I rephrase the prompt?" (context-engineering-principles: "Debug context, not prompts").

## The three layers

Don't duplicate what a lower layer already captures.

### Layer 1: Claude Code OTel (infrastructure)

Built-in OpenTelemetry via `CLAUDE_CODE_ENABLE_TELEMETRY=1`. Don't reimplement these signals.

| Signal | Fields |
|--------|--------|
| `claude_code.token.usage` | type (input/output/cacheRead/cacheCreation), model |
| `claude_code.cost.usage` | per API request, by model |
| `claude_code.tool_result` | tool_name, success, duration_ms, error, decision_type |
| `claude_code.api_request` | model, cost_usd, duration_ms, input/output tokens |
| `claude_code.api_error` | error, status_code, duration_ms, attempt |
| `prompt.id` | Correlates all events from one user prompt |

Use for token costs, tool success rates, latency, cost-per-model. Ref: [Monitoring](https://code.claude.com/docs/en/monitoring-usage.md)

### Layer 2: Agent SDK hooks and cost tracking (programmatic)

Application-specific signals OTel can't capture.

**ResultMessage** (every `query()`): `total_cost_usd`, `usage` dict, `num_turns`, `session_id`, `subtype` (success/error_max_turns/error_max_budget_usd/error_during_execution), `stop_reason`. Python SDK: cumulative totals only.

**Hooks** (in-process, no context cost):

| Hook | Use |
|------|-----|
| `PostToolUse` | Audit logging (tool_name, result) |
| `SubagentStart`/`SubagentStop` | Fork lifecycle tracking |
| `PreCompact` | Archive pre-compaction context |
| `Stop` | Session outcome capture |
| `Notification` | Forward status externally |

Observability hooks must return `{"async_": True}` — async hooks can't modify behavior, only observe. Ref: [Agent loop](https://platform.claude.com/docs/en/agent-sdk/agent-loop.md), [Hooks](https://platform.claude.com/docs/en/agent-sdk/hooks.md), [Cost tracking](https://platform.claude.com/docs/en/agent-sdk/cost-tracking.md)

### Layer 3: ollim-bot application state (domain)

File-based, git-tracked in `~/.ollim-bot/state/`. Readable without running the bot.

| File | Captures |
|------|----------|
| `session_history.jsonl` | Lifecycle: `created`, `compacted`, `swapped`, `cleared`, `interactive_fork`, `bg_fork`, `isolated_bg` (session_id, timestamp, parent_session_id) |
| `ping_budget.json` | available/capacity, refill_rate, daily_used, critical_used |
| `pending_updates.json` | Fork→main context channel (capped at 10, sentinel on overflow) |
| `fork_messages.json` | Discord message ID → fork session (7-day TTL) |

**Prompt tags** identify session type in transcripts: `[routine-bg:ID]`, `[reminder-bg:ID]`, `[webhook:ID]`, `[fork-started]`. Searchable via `claude-history`.

**Bg fork preamble** (`build_bg_preamble()`): ping instructions, update mode, busy state, budget/schedule, tool restrictions, skills — the primary debugging artifact for bg fork behavior.

**Context warnings**: 60% and 80% of 200k window. Ref: [Context flow](https://docs.ollim.ai/architecture/context-flow), [Sessions](https://docs.ollim.ai/architecture/session-management)

## Diagnostic decision tree

When auditing, map the symptom to the responsible layer and files.

| Symptom | Layer | Check | Gap pattern |
|---------|-------|-------|-------------|
| Can't tell why a bg fork was silent | L3 | `session_history.jsonl` for `bg_fork` event; transcript via `claude-history` using prompt tag | Missing: fork outcome event, `BgForkTracking` not persisted |
| Can't tell what triggered a bg fork | L3 | `session_history.jsonl` `bg_fork` event fields | Missing: `trigger_type` field (routine/reminder/webhook) on the session event — must search transcripts for prompt tag to recover |
| Can't reconstruct what a bg fork saw | L3 | `build_bg_preamble()` output; every input in the **Preamble inputs** table below | Missing: preamble snapshot at dispatch time; see table for per-input persistence status |
| Ping happened but shouldn't have (or vice versa) | L3 | `ping_budget.json` counters; busy state at fork time | Missing: per-event journal (deduction source, busy-block, refill timestamps) |
| Webhook triggered but nothing happened | L3 | `webhook.py` logs; `session_history.jsonl` for matching `bg_fork` | Missing: webhook acceptance log, auth/validation rejection log, task error callback |
| Fork started but exit is missing | L3 | `session_history.jsonl` for `interactive_fork`; exit action | Missing: `fork_exited` event with exit action (SAVE/REPORT/EXIT) |
| Cost spike on bg forks | L1+L2 | OTel `api_request` by model; `ResultMessage.num_turns` | Check: tool denial rate forcing extra turns; model override in routine YAML |
| Agent ignored a reminder/routine | L3 | Scheduler logs; `session_history.jsonl` for expected `bg_fork` | Missing: structured dispatch event; check `validate_dispatch` rejection |
| State file doesn't match expected | L3 | `git log` on `~/.ollim-bot/state/`; diff against expected | Snapshot overwritten without journaling (P4 violation) |

### Preamble inputs (ephemeral risk)

Every input to `build_bg_preamble()` and its downstream assembly. When auditing preamble reconstructability, check each row — ephemeral inputs are the gaps.

| Input | Source | Persisted? | Why it matters |
|-------|--------|------------|----------------|
| Busy flag | `agent.lock().locked()` at dispatch | No — runtime only | Determines "user is mid-conversation" warning; changes ping behavior |
| Ping budget snapshot | `ping_budget.json` at dispatch time | Overwritten on refill/deduction | Fork's ping/no-ping decision depended on these values |
| Chain context (depth, max_chain) | Reminder `.md` frontmatter at fork time | Volatile — `.md` reflects *current* chain state, not fork-time state | Fork sees chain depth N but file may show N+1 by inspection time |
| Overdue/late tag | Computed from `overdue_at` param in `build_reminder_prompt()` | No — computed, never persisted | Affects urgency framing in preamble |
| Pending updates | `pending_updates.json` — popped on read by main session | Consumed — may be gone by inspection | Fork peeked N updates; main session may have already popped them |
| Skills section | `build_skills_section()` output, appended downstream | No — assembled at dispatch | Which skills were injected affects fork capabilities |
| Upcoming schedule | `build_upcoming_schedule()` using `datetime.now(TZ)` | No — computed from cron + current time | Selected entries and fire times not persisted |
| `BgForkConfig` (allowed_tools) | `from_item()` merges `build_bg_tools()` + strips `GATED_TOOLS` | No — reconstructable from source + YAML but fragile across code changes | Actual tool restrictions the fork operated under |
| Preamble string | Final assembled text from `build_bg_preamble()` | No — never persisted | The primary debugging artifact; re-running with same inputs may not reproduce it |

**Remediation pattern**: snapshot preamble inputs as a structured JSONL entry alongside the `bg_fork` session event in `forks.py`. Fields: `busy`, `ping_budget_snapshot`, `bg_config`, `schedule_entry_ids`, `chain_depth`, `pending_update_count`, `skills`, `preamble_hash`.

## Metrics and the improvement loop

Observe → measure → identify pattern → change → re-measure.

| Metric | Source file/field | When to act |
|--------|-------------------|-------------|
| Cost per interaction type | `ResultMessage.total_cost_usd`, grouped by `session_history.jsonl` event type | Bg fork cost > $0.05 → check `model` in routine YAML, tool denial rate |
| Turns per bg fork | `ResultMessage.num_turns` | > 5 turns → tool restrictions forcing retries, or prompt too vague |
| Bg fork outcome ratio | Transcript ping vs. `pending_updates.json` entries | Report-to-ping < 1:1 → routine making poor triage decisions |
| Compaction frequency | `session_history.jsonl` `compacted` count per day | > 3/day → `/compact` proactively or `/clear` between topics |
| Tool denial rate | OTel `tool_result` (decision_type=reject) | > 20% → expand `allowed-tools` in routine YAML or sharpen prompt |
| Ping budget efficiency | `ping_budget.json` `critical_used` / `daily_used` | Critical > 30% of total → routines misjudging urgency |
| Busy-blocked rate | Non-critical pings returning error during `agent.lock()` | > 2/day → shift routine cron away from active-usage hours |
| Cache hit ratio | OTel `cache_read_input_tokens` / `input_tokens` | < 50% in forks → prompt structure varying too much between turns |
| Fork concurrency | `session_history.jsonl` overlapping `bg_fork` timestamps | > 2 concurrent → check scheduler overlap; risk of state file race |
| Pending update overflow | `pending_updates.json` sentinel frequency | Sentinel appearing → forks producing updates faster than main consumes |
| Time-to-first-message | Interactive fork: `interactive_fork` event → first Discord message | > 10s → fork startup overhead; check preamble assembly cost |

## Principles

Decision-boundary principles for ambiguous cases (the layers section covers *what* to log; these cover *when* and *how*):

1. **Log inputs, not just outputs** — when a fork misbehaves, the first question is "what did it see?" Log preamble contents, tool restrictions, pending updates, and context % at dispatch time.
2. **Transitions over snapshots** — if a state file is overwritten (e.g., `ping_budget.json`), the previous value is lost. Append-only JSONL journals preserve the trail. Test: can you answer "what was the value at time T?"
3. **Structured over freeform** — `log.info("bg fork started: %s", tag)` is unsearchable. `{"event": "bg_fork_started", "tag": tag, "session_id": sid}` enables queries. Every log call should have structured fields.
4. **Observable at rest** — every debugging question answerable from `~/.ollim-bot/state/` + `git log` without running the bot or querying OTel. If you need a live process to answer it, add a state file.
5. **Async for side effects** — observability hooks return `{"async_": True}` or use `asyncio.create_task`. Never block the agent loop.

## Audit checklist

For each item: check the specific files/fields listed. Mark pass/fail explicitly (e.g., `[x]`/`[ ]`) with file:line citations inline — not in a separate recommendations section. For each failing item, provide a **distinct** recommendation naming the specific file and call site — do not consolidate into one vague block.

**Cross-layer attribution**: when a gap exists at one layer, note whether partial visibility exists at another. Example: busy-block denials are visible in L1 OTel `tool_result` (when telemetry enabled) but not persisted to L3 state files — both facts matter for the audit.

**Positive findings**: briefly note what IS already observable for each checklist area (e.g., "git-tracked YAML, prompt tags, and dispatch timestamps are reconstructable") before listing gaps. This grounds the audit and prevents overstatement of missing coverage.

**Exhaustive call-site coverage**: for the audited module, enumerate every public function and every state-mutating call site before assessing gaps. A missing call site is a missing gap — grep the module for all functions that write state, send messages, or make decisions, and account for each in the audit.

- [ ] **Layer identified**: feature uses the right layer (OTel for costs/latency, hooks for SDK events, L3 state files for domain). Gap: reimplementing what OTel already captures, or using `log.info` for data that belongs in a state file.
- [ ] **Context assembly observable**: can reconstruct `build_bg_preamble()` output from state files. Check every row in the **Preamble inputs** table — each ephemeral input is a potential gap. Common misses: chain context (volatile `.md`), overdue/late tag (computed, never persisted), pending updates (consumed on read), skills section (assembled at dispatch). Gap: any preamble input marked "No" or "Volatile" in the table that lacks a persistence mechanism.
- [ ] **Fork traceable end-to-end**: routine/reminder `.md` file → `session_history.jsonl` `bg_fork`/`interactive_fork` event (with `parent_session_id`) → prompt tag (`[routine-bg:ID]`) → transcript via `claude-history` → `fork_messages.json` → Discord output. Two common gaps: (1) missing exit event with exit action (SAVE/REPORT/EXIT), (2) missing `trigger_type` field (routine/reminder/webhook) on the `bg_fork` session event — without this, determining what triggered a fork requires searching transcripts for prompt tags.
- [ ] **Transitions journaled**: first, enumerate every function in the audited module that writes to or overwrites a state file (grep for `json.dump`, `write_md`, `open(..., 'w')`, `save()`, or equivalent). Then check whether each write site uses append-only JSONL with timestamps and source attribution. Gap: any mutation site that overwrites previous values without journaling (e.g., `ping_budget.json` counters via `try_use`, `_refill`, `_reset_daily`, `set_capacity`, `set_refill_rate` — each is a distinct gap if unjournaled).
- [ ] **Failures visible**: denials (OTel `tool_result` or `PostToolUse`), budget exhaustion (`ping_budget.json`), timeouts (`forks.py` timeout log), compaction (`session_history.jsonl`), busy-blocks (`agent_tools.py` error returns). Gap: failure returned to agent as tool result but not persisted to state files.
- [ ] **No silent drops**: capped pending updates (`pending_updates.json` sentinel), restricted tools (`BgForkConfig.allowed_tools`), skipped preamble sections, background task exceptions (`asyncio.Task` without error callback). Gap: omission happens without any log entry.
- [ ] **Non-blocking**: observability hooks return `{"async_": True}`, logging uses `asyncio.create_task` or synchronous file I/O on small files. Gap: awaiting network I/O or heavy processing in the agent loop path.

## Related skills

| Skill | Relationship |
|-------|-------------|
| `context-engineering-principles` | Upstream — designs context flow; this verifies what actually flowed |
| `debug-bot-history` | Downstream — investigates using signals this skill ensures exist |
| `systematic-debugging` | Orthogonal — general debugging; this is agent-observability specific |
