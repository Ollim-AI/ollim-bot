# Philosophy Audit

Audit of the current feature set against the five stated design principles.
Conducted 2026-02-28.

## The Five Principles

1. **Context quality is the product**
2. **Proactive over reactive**
3. **Meet the user where they are**
4. **Files as shared language**
5. **Single-user by design**

## Strong Alignments

Features that cleanly serve the stated philosophy:

| Feature | Principle Served | Why It Fits |
|---------|-----------------|-------------|
| Persistent sessions + compaction | Context quality | Conversation carries across restarts; compaction preserves signal |
| Interactive forks with selective persistence | Context quality | Main session stays focused; user controls what context survives |
| Background forks (disposable) | Context quality | Scheduled work never pollutes the main conversation |
| Routines + reminders | Proactive | Bot reaches out on schedule — user doesn't have to remember |
| Follow-up chains | Proactive | Agent can autonomously schedule check-ins without user action |
| Ping budget | Proactive (with guardrails) | Prevents proactivity from becoming spam |
| Discord-only surface | Meet where they are | No new app to install or check |
| Google Tasks/Calendar/Gmail | Meet where they are | Integrates existing tools, doesn't replace them |
| Markdown routines/reminders | Files as shared language | Both human and agent read/write the same .md files |
| Git auto-commit on data writes | Files as shared language | Full version history, human-auditable |
| No auth, no multi-tenancy | Single-user | Radical simplification from not pretending to be multi-user |
| User-proxy subagent | Context quality + single-user | Deep personal preference modeling only possible for one user |

## Tensions and Contradictions

### 1. Webhook input security is multi-user paranoia in a single-user system

The 4-layer webhook security (JSON Schema, content fencing, Haiku screening,
operational limits) is thorough — but the stated principle is "single-user by
design." External webhook callers are services the user configured,
authenticated by a bearer token the user set. The Haiku screening layer
(checking for injection in every string) treats the user's own integrations as
adversarial. This adds latency and cost to every webhook invocation for a threat
that barely exists in a single-user system where the user controls both ends.

Counter-argument: Webhooks accept external data, so defense-in-depth is
reasonable. But the Haiku screening feels like it crosses from "careful" into
"doesn't trust its own operator."

### 2. Permission modes add complexity that contradicts single-user simplicity

Four permission modes (`dontAsk`, `default`, `acceptEdits`,
`bypassPermissions`) plus Discord reaction-based approval is a sophisticated
access control system for a bot with exactly one user. The default mode
(`dontAsk`) silently denies non-whitelisted tools — the user doesn't even know
the agent tried. This conflicts with "context quality is the product" because
silent denials mean the agent operates with an invisible handicap.

The tension: A single-user system should either trust its user (and by
extension, the agent the user configured) or surface denials clearly. Silent
denial is a multi-user pattern leaking into a single-user design.

### 3. `update_main_session` complexity works against "files as shared language"

Background forks have four update modes (`always`, `on_ping`, `freely`,
`blocked`) that control whether results flow back to the main session. This is a
code-level concept that isn't visible in the routine/reminder markdown files in
an intuitive way. A user reading `update_main_session: on_ping` in their routine
YAML needs to understand the fork architecture to know what that means. The
"shared language" principle suggests this should be more transparent.

### 4. Subagent isolation vs. context quality

The gmail-reader, history-reviewer, and responsiveness-reviewer subagents each
operate in isolated contexts without access to the main session's conversation.
This means the gmail-reader triages email without knowing what the user is
currently working on. A contextually-aware email triage (which the "context
quality" principle would suggest) would need main session context — but
subagents are deliberately isolated.

This is a known tradeoff: isolation prevents context pollution, but it also
prevents context-informed judgment.

## Gaps: Philosophy Suggests Features That Don't Exist

### 1. No proactive context refresh

"Context quality is the product" + "proactive over reactive" together suggest
the bot should proactively maintain its own context quality — noticing when its
understanding is getting stale and asking for updates. Currently, context quality
degrades passively through compaction and session age, and the user has to
manually `/compact` or `/clear`. A routine that audits context quality would
close this gap.

### 2. No "meet the user where they are" beyond Discord + Google

The principle says "integrate with existing tools, not new surfaces" — but the
only integrations are Discord (surface) and Google (Tasks, Calendar, Gmail
read-only). If the user's work life involves GitHub, Slack, Linear, or other
tools, the bot can't proactively surface information from those contexts. The
webhook system partially addresses this (external systems can push to the bot),
but it's reactive — the opposite of the stated philosophy.

This may be intentional scope limitation ("quality over breadth"), but it's
worth noting the philosophy implies more integration surface than exists.

### 3. No learning loop or preference evolution

"Single-user by design" enables deep personalization, but there's no mechanism
for the bot to learn from user behavior over time. The user-proxy subagent reads
static files, but there's no feedback loop where the bot updates its
understanding of the user based on interaction patterns. The
responsiveness-reviewer subagent analyzes engagement, but it only suggests
schedule changes — it doesn't autonomously adapt.

### 4. Gmail is read-only — can't "meet the user" for email actions

The Gmail integration is read-only (`gmail.readonly` scope). The bot can triage
email but can't draft replies, archive, label, or take action. If "meet the user
where they are" means reducing context switches, the user still has to switch to
Gmail for every action the bot recommends. Compare this to Google Tasks and
Calendar, which have full read/write.

This is likely a deliberate scope choice (email actions are high-risk), but it's
a gap relative to the philosophy.

## Features That Seem Over-Engineered Relative to Philosophy

### 1. Ping budget's fractional refill math

The ping budget tracks `available` as a float with fractional refill
accumulation, daily counters, critical counters, and reset dates. For a
single-user system with a default capacity of 5, this is more mechanism than the
problem warrants. A simple "N pings per time window" counter would serve the
same purpose with less cognitive overhead for the user trying to understand why a
notification didn't arrive.

### 2. Session history lifecycle tracking

Seven distinct lifecycle event types (`created`, `compacted`, `swapped`,
`cleared`, `interactive_fork`, `bg_fork`, `isolated_bg`) with parent session
lineage tracking. This is valuable for debugging but seems like infrastructure
for a team-operated service, not a single-user bot. The "files as shared
language" principle is weakened when the files are JSONL lifecycle logs that only
a developer would read.

## Summary Verdict

The feature set is **strongly aligned** with the stated philosophy overall. The
core loop — persistent context, proactive scheduling, fork-based context
management, Discord-native interaction, file-based storage — is coherent and
principled.

The main tensions are:

1. **Security posture overfit** — Webhook screening and permission modes carry
   multi-user assumptions into a single-user system
2. **Subagent isolation vs. context quality** — A known tradeoff, but worth
   being explicit about
3. **Integration surface is narrower than "meet them where they are" implies** —
   Only Discord + Google; the philosophy gestures at broader integration
4. **No proactive context maintenance** — The bot is proactive about tasks but
   passive about its own context quality

None of these are architectural problems — they're calibration questions about
where the design sits on spectrums the philosophy defines. The strongest signal
is that the philosophy is genuinely lived in the codebase, not just aspirational.
