---
name: improve-routine
description: Diagnose and fix routine quality issues — data source confusion, embellishment propagation, model/tool mismatches, report quality. Use when a routine produces wrong results, pings at bad times, reports inaccurate data, or needs structural fixes. Not for creating new routines.
argument-hint: routines/routine-name.md
disable-model-invocation: true
---

# Improve Routine

Use `EnterPlanMode` immediately — Phases 1–2 are read-only. `ExitPlanMode` at end of Phase 2 before fixing.

Diagnose failures → design fixes → apply and verify. Never rewrite without user sign-off.

**Diagnostic discipline**: A false diagnosis that causes an unnecessary edit is costlier than a missed finding the user can report later. When evidence is ambiguous, mark N/A.

Target: $ARGUMENTS (!`wc -l < "$ARGUMENTS"` lines)

## Phase 1: Diagnose (plan mode)

### 1. Read

Read the target routine and all files it references (data sources, profiles, logs). Also read the routine's preamble config by checking its YAML frontmatter fields (`update-main-session`, `allow-ping`, `allowed-tools`, `model`, `skills`).

Classify:
- **Type**: notifier (pings user with findings) | stabilizer (silent maintenance) | aggregator (collects from multiple sources) | delegator (uses subagents)
- **Ping behavior**: always-ping | conditional | silent (`allow-ping: false`)
- **Data sources**: list every file, API, or tool the routine reads from

### 2. Identify failures

Use `AskUserQuestion`: "What problems have you experienced with this routine? What does it get wrong, or what triggers it shouldn't?"

Options:
- **Specific failures** — user describes concrete problems → reactive mode (step 3a)
- **General improvement** — user says "make it better" → proactive mode (step 3b)
- **Both** — reactive first, then proactive scan

### 3a. Reactive mode (failure-driven)

Investigate the user's reported failures:
- Read the routine carefully — locate the steps responsible for each failure
- If available: check session history for recent runs (`!claude-history search [routine-name]`)
- For each failure, identify the root cause using the failure modes reference below

### 3b. Proactive mode (structural scan)

When the user has no specific failures, scan for problems they might not notice. ultrathink

Execute these sub-scans in order:

**3b-i. Data source scan (D)**: For each D code, state whether it applies or N/A. For presence-based findings, quote the routine text. For absence-based findings, state what's missing. Classify as OBSERVED or INFERRED. Output a findings table.

**3b-ii. Reporting scan (R)**: Same process (per-code evidence, OBSERVED/INFERRED, findings table) for R codes.

**3b-iii. Configuration scan (C)**: Same process (per-code evidence, OBSERVED/INFERRED, findings table) for C codes.

**3b-iv. Prompt quality scan (P)**: Same process (per-code evidence, OBSERVED/INFERRED, findings table) for P codes.

**3b-v. Diagnostic filter**: For each finding marked "applies," ultrathink: construct a concrete scenario — specific trigger → specific agent behavior with this problem present vs. absent. Drop findings where the delta isn't demonstrable. Present surviving findings with one-line scenario justification.

Present surviving findings to user. They select which to address.

### 4. Produce failure report

| # | Failure | Root cause | Failure mode | Acceptance criterion |
|---|---------|-----------|-------------|---------------------|
| 1 | one-line description | why it happens | code | how to confirm the fix worked |

Use `AskUserQuestion`: Present the failure report. Ask:
- Any to dispute, deprioritize, or add?
- For 5+ failures: confirm fix-all vs. targeted fixes only

## Phase 2: Design (plan mode)

### 5. Fetch relevant docs

`WebFetch` https://docs.ollim.ai/routines for the routine format spec. If fetch fails, use `SearchOllimBot` for "routine format" instead. Then conditionally:

| Failure involves... | Fetch |
|--------------------|------|
| Preamble/report quality | Read `src/ollim_bot/scheduling/preamble.py` |
| Tool restrictions | Read `src/ollim_bot/tool_policy.py` |
| Scheduler behavior | Read `src/ollim_bot/scheduling/scheduler.py` |

### 6. Design fixes

For each diagnosed failure, design a targeted fix:
- Ground the fix in fetched docs or source code
- Check the fix doesn't introduce a new failure mode
- If two fixes conflict, keep the one with stronger grounding

Present the fix plan:

| # | Failure | Fix | Source ref | Acceptance criterion |
|---|---------|-----|-----------|---------------------|
| 1 | from failure report | concrete change | file + section | from failure report |

### 6b. Counterfactual analysis

For each proposed fix, ultrathink: would the routine produce worse outcomes without this fix? Construct a concrete scenario, trace what happens with and without. Eliminate fixes where the benefit isn't real.

Use `AskUserQuestion`: Present fixes for approval.

Then `ExitPlanMode`.

## Phase 3: Fix + Verify (write mode)

### 7. Apply fixes

Execute approved fixes with Edit. Priority: **Correctness > Substance > Brevity**.

### 8. Verify (independent critics)

Spawn 2 parallel critic subagents via `Agent`:

**Critic 1 — Completeness**: "Read the failure report below and the rewritten routine at [path]. Run `git diff HEAD -- [path]`. For each diagnosed failure, explain how the changed lines prevent the failure scenario from the report. Report ADDRESSED (with mechanism), INSUFFICIENT (change exists but doesn't demonstrably prevent the failure), or MISSING (no relevant change)."

**Critic 2 — Regression**: "Read the Failure Modes Reference in this skill and the rewritten routine at [path]. Run `git diff HEAD -- [path]`. For each failure mode code, check if the diff introduces that failure where it didn't exist before. Report NEW or OK."

After both return: aggregate findings, present before/after for each diagnosed failure.

---

## Failure Modes Reference

### D: Data sources — how the routine gets information

- **D1. Absence-as-evidence** — empty results from source → negative conclusion. Routine treats "no entries" as "didn't happen" instead of "no visibility."
  - *Grounded in*: Music practice reported "14-day gap" from empty conversation history when user practiced offline.
  - *Applies when*: Routine draws conclusions from empty query results.
  - *Skip when*: Routine reports the gap without interpreting it ("no entries in log" not "no practice").

- **D2. Unspecified data source** — "check if user practiced" without naming file/API/tool. Agent falls back to conversation history or training priors.
  - *Grounded in*: Early music-practice lacked explicit `practice-log.md` reference.
  - *Applies when*: Routine references user state without a file path or CLI command.
  - *Skip when*: Every state check names a specific source.

- **D3. Conversation-history-as-ground-truth** — bg forks have no conversation history. Even main-session history is incomplete (compaction, resets).
  - *Grounded in*: Music practice follow-up relied on history-reviewer for practice detection.
  - *Applies when*: Routine uses history to determine what the user *did* (not what they *said*).
  - *Skip when*: History used only for preferences/tone, or delegated to history-reviewer with caveats.

- **D4. Cross-routine data contamination** — Routine A writes interpreted data to shared file (USER.md); Routine B reads as ground truth.
  - *Grounded in*: identity-stabilize wrote "back-to-back DJ sets" from agent summary into USER.md.
  - *Applies when*: Routine writes to a shared file based on agent-generated summaries.
  - *Skip when*: Writes only to routine-scoped files with structured entries, not prose.

- **D5. Missing freshness signal** — reads data file without checking when last updated. Stale data produces inaccurate time-bounded analysis.
  - *Applies when*: Routine produces time-bounded analysis ("this week", "last 24 hours").
  - *Skip when*: Routine checks entry dates and caveats stale data.

### R: Reporting — how findings are summarized back

- **R1. Embellished reporting** — agent adds color/confidence beyond source data when writing to persistent files.
  - *Grounded in*: identity-stabilize propagated "back-to-back DJ sets" from embellished summary.
  - *Applies when*: Routine summarizes or interprets findings before writing to a persistent file.
  - *Skip when*: Routine writes structured data (dates, numbers) rather than prose.

- **R2. Unattributed claims** — report_updates without naming sources. Main session can't verify or weight claims.
  - *Applies when*: Routine calls report_updates with factual claims.
  - *Skip when*: Report is purely structural ("stabilized: added X, removed Y").

- **R3. Ping-when-should-report** — informational summaries sent as ping instead of report_updates. Wastes ping budget.
  - *Applies when*: Routine has conditional notification logic.
  - *Skip when*: Routine always pings (it's the purpose) or never pings.

### C: Configuration — YAML frontmatter and tool access

- **C1. Wrong model for task** — Haiku/Sonnet for tasks requiring nuance, taste, or complex reasoning.
  - *Grounded in*: morning-music on Haiku searched "tech house" instead of techno.
  - *Applies when*: `model: haiku` or `model: sonnet` with subjective/creative tasks.
  - *Skip when*: Task is mechanical (aggregation, stabilization). Default (no model) inherits main session model.

- **C2. Unscoped tool access** — bare Bash/Write/Edit without path restrictions in allowed-tools.
  - *Applies when*: allowed-tools includes broad tools without parenthetical scope.
  - *Skip when*: All tools scoped (e.g., `Write(./practice-log.md)`, `Bash(ollim-bot *)`).

- **C3. Dangerous tool combination** — delegation (Task/Agent) + unscoped writes to shared files.
  - *Grounded in*: identity-stabilize's write-from-agent-summary pattern.
  - *Applies when*: allowed-tools includes both delegation and unscoped Write/Edit.
  - *Skip when*: Writes scoped to routine-owned files.

### P: Prompt quality — the routine message itself

- **P1. Vague action verbs** — "check", "review", "look at" without naming the tool or command.
  - *Applies when*: Routine uses generic verbs for data gathering.
  - *Skip when*: Every gather step names a specific tool or CLI command.

- **P2. Missing recovery path** — gather steps that can fail with no failure handling instruction.
  - *Applies when*: Routine gathers from 2+ sources where any could fail.
  - *Skip when*: Explicit failure handling per gather step, or single infallible source.

- **P3. Sequencing violation** — notify before data gathering complete.
  - *Applies when*: Routine has both data gathering and notification steps.
  - *Skip when*: Routine explicitly sequences gather-before-notify.

- **P4. Preamble conflict** — unconditional instructions contradicting conditional preamble (busy state, budget).
  - *Applies when*: Routine has unconditional notification instructions ("always send an embed").
  - *Skip when*: Routine uses conditional language or defers to preamble.

- **P5. Missing idempotency guard** — double-fire produces duplicate artifacts.
  - *Applies when*: Routine creates persistent artifacts (reminders, log entries, tasks).
  - *Skip when*: Output is naturally idempotent or routine checks before writing.
