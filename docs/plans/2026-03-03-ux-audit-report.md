# UX Audit Report: Missed Improvement Opportunities

**Date**: 2026-03-03
**Method**: 3 reviewers (proactive, interaction, continuity) investigated 9 surfaces
with adversarial cross-review. Findings deduplicated and ranked. Independently
confirmed findings marked with reviewer count.

**Evaluation framework**: Project's own `ux-principles` skill — hard rules (High),
strong defaults (Medium), polish (Low).

---

## HIGH — Violates hard rules (5 findings)

### 1. `on_message` has no error handling — eyes reaction sticks on failure

`bot.py:289-339` — no try/except around the main handler. If `stream_chat()`
raises (CLIConnectionError, auth expiry, anything), the eyes reaction stays on
the user's message permanently. User gets no error message, no indication the
bot failed.

- **Principle**: "Acknowledge instantly" / "Promise only what exists"
- **Fix**: Wrap `_dispatch()` in try/except; on error, remove eyes reaction and
  send `"something went wrong."`

### 2. Runtime OAuth expiry has no detection or recovery

`main.py:226-229` — auth checked once at startup. Mid-session token expiry
causes CLIConnectionError that propagates uncaught through finding #1 above. Bot
silently hangs on next message.

- **Principle**: "Promise only what exists"
- **Fix**: Catch CLIConnectionError in the error handler from #1; attempt re-auth
  flow (DM login URL).

### 3. `on_app_command_error` re-raises non-CheckFailure exceptions (2x confirmed)

`bot.py:436-445` — only CheckFailure handled. Any other slash command exception
shows Discord's opaque "The application did not respond." If a response was
already sent (e.g., `/compact`'s "compacting..."), the user gets an orphaned
message with no error explanation.

- **Principle**: "Degradation messages are plain language, not errors"
- **Fix**: Add catch-all: log error, send ephemeral `"something went wrong."` if
  interaction not yet responded to.
- **Confirmed by**: ux-interaction, ux-proactive

### 4. `/thinking` (and `/model`) while in fork silently kills the fork (2x confirmed)

`agent.py:139-153` — `set_thinking()` drops `_fork_client` without calling
`exit_interactive_fork()`. No fork exit embed sent, fork entry buttons become
dead ends. State desync: `_in_interactive_fork` may not be cleared. Same issue
exists for `/model` via `set_model()`.

- **Principle**: "Context survives boundaries" / "Promise only what exists"
- **Fix**: Before dropping client, check `in_fork`; either block with ephemeral
  "exit fork first" or call proper `exit_interactive_fork(EXIT)` with embed.
- **Confirmed by**: ux-interaction, ux-continuity

### 5. Reply-to-fork silently degrades after 7-day TTL

`sessions.py:110`, `bot.py:309-316` — Discord messages persist forever but the
session mapping expires after 7 days. User replies to an old bg fork message
expecting to resume that conversation; instead gets a main-session response with
quoted context and zero indication that fork resumption failed.

- **Principle**: "Promise only what exists" / "Degradation messages are plain language"
- **Fix**: When reply targets a message whose TTL has expired, send ephemeral
  `"this session has expired — starting fresh with quoted context."`

---

## MEDIUM — Misses strong defaults (19 findings)

### 6. Fork exit embed: action encoded in color only, EXIT has no description (3x confirmed)

`embeds.py:40-52` — all three exit strategies produce "Fork Ended" with only
color differentiating them. EXIT has no description at all. Gray reads as
"failed/cancelled" rather than "clean exit." Color is not accessible.

- **Fix**: Include action in title: `"Fork Ended — saved to main"` /
  `"Fork Ended — summary queued"` / `"Fork Ended — discarded"`
- **Confirmed by**: ux-proactive, ux-interaction, ux-continuity

### 7. Reconnect greeting "i remember where we left off" overpromises (2x confirmed)

`bot.py:284` — sent whenever `load_session_id()` returns non-None. But session
may be heavily compacted, expired on CLI side, or left over from a crashed fork.
Session ID existence does not equal functional memory.

- **Fix**: `"hey, i'm back. picking up where we left off."` — softer claim, or
  skip continuity promise entirely.
- **Confirmed by**: ux-interaction, ux-continuity

### 8. Bg fork failure notification exposes internal tag format (2x confirmed)

`forks.py:117-119` — user sees
`"Background task failed: \`[routine-bg:morning-checkin]\` -- check logs for details."`
Internal tag format + impossible instruction.

- **Fix**: Use routine/reminder's human `description` field. Remove "check logs."
- **Confirmed by**: ux-proactive, ux-interaction

### 9. Image reading before eyes reaction delays acknowledgment

`bot.py:300` vs `:318` — `_read_images()` runs before
`add_reaction("\N{EYES}")`. For large image attachments, the 500ms
acknowledgment window is missed.

- **Fix**: Move `add_reaction` before image reading.

### 10. Non-discord MCP tool labels show raw internal names

`formatting.py:32-33` — only `mcp__discord__` prefix is stripped.
`mcp__docs__SearchOllimBot` and any future MCP server shows the full raw
internal name to the user.

- **Fix**: Strip `mcp__<server>__` prefix generically for all MCP namespaces.

### 11. `/compact` leaves "compacting..." artifact (2x confirmed)

`bot.py:183-186` — sends `"compacting..."` then followup with stats. Two
permanent messages. `/cost` correctly uses `defer(thinking=True)` + one followup.

- **Fix**: Use same `defer()` pattern as `/cost`.
- **Confirmed by**: ux-interaction, ux-continuity

### 12. `/config` value parameter has no autocomplete

`bot.py:399-434` — user must guess valid values (e.g., "opus"/"sonnet"/"haiku"
for model keys). Error only shown after submission. Compare `/model` which uses
a choices dropdown.

- **Fix**: Per-key value hints in `describe()`, or dynamic autocomplete based on
  selected key.

### 13. Stale reminder fires with no overdue signal

`scheduler.py:237-241` — `if run_at < now: run_at = now + 5s`. A reminder for
"3pm report" firing at 5pm gives the agent no context that it's late. The nudge
feels broken or arbitrary.

- **Fix**: Inject `"[late: was scheduled for 3:00 PM]"` into prompt so agent can
  acknowledge the delay.

### 14. No guaranteed confirmation after reminder creation

`prompts.py:96-107` — system prompt doesn't instruct the agent to confirm after
creating a reminder. ADHD user says "remind me at 3pm to call the doctor" and
may get no visible confirmation.

- **Fix**: Add to system prompt: "after creating a reminder, always echo the
  scheduled time in one line."

### 15. Pending updates lack user visibility (2x confirmed)

`forks.py:49-61`, `agent_context.py:67-88` — updates from bg forks are pull-only
(injected on next user message). No push signal that updates are waiting. When
the agent surfaces them, there's no tag distinguishing bg updates from regular
response content.

- **Fix**: For `always` mode, lightweight nudge after bg fork:
  `"bg update ready."` When prepending updates, add
  `-# (catching you up on background activity...)` before the agent streams.
- **Confirmed by**: ux-proactive, ux-continuity

### 16. `/clear` during active fork silently discards fork

`agent.py:121-129`, `bot.py:177` — fork exited with `ForkExitAction.EXIT` (no
embed, no summary). Confirmation `"conversation cleared. fresh start."` mentions
nothing about the lost fork. Message is non-ephemeral.

- **Fix**: If `in_fork`, mention both: `"fork discarded, conversation cleared."`
  Make ephemeral.

### 17. Fork idle timeout invisible until agent streams

`scheduler.py:287-316` — both soft and hard timeout prompts are injected as
agent prompts. User sees nothing until the agent finishes generating. Hard
timeout at 20min forces exit while user is AFK with no prior visible warning.

- **Fix**: Before agent prompt, send brief user-visible signal:
  `-# fork idle — checking in...`

### 18. Approval timeout message says "timed out" exposing implementation

`permissions.py:152` — `"~~\`{label}\`~~ — timed out"` reveals the 60-second
window as machinery.

- **Fix**: Change to `"— expired"` or `"— not approved"`.

### 19. Reply-to-fork silently dropped when already in a fork

`bot.py:307-308` — `if fork_session_id and agent.in_fork: fork_session_id = None`.
User's intent to resume a bg fork is discarded with no notification.

- **Fix**: Ephemeral
  `"already in a fork — this reply was added as context instead."`

### 20. "Dismiss" button: ambiguous label + missing interaction acknowledgment

`views.py:151-153` — "Dismiss" means "delete this message for everyone" but the
label implies "dismiss from my view." Also, `interaction.response` is never
called before `message.delete()`, causing a brief "This interaction failed"
flash.

- **Fix**: Rename to "Close" or "Delete." Add `await interaction.response.defer()`
  before the delete.

### 21. No button count limit in `discord_embed` schema — agent can overwhelm

`agent_tools.py:137`, `embeds.py:147` — schema has no `maxItems` on buttons
array. Agent can produce 25 buttons (5 rows) for a task list. Violates "one
action, not a menu."

- **Fix**: Add `maxItems: 5` to schema + prompt guidance: "3-5 buttons per embed
  max."

### 22. Agent inquiry peek+pop race allows double-invocation; consumed buttons stay active

`views.py:112-128` — `peek()` then `pop()` is not atomic. Concurrent clicks can
both pass the check. Also, consumed buttons remain visually active — second click
shows "expired" with no prior signal.

- **Fix**: Use single `pop()` instead of `peek()+pop()`. Edit original message to
  disable button after use.

### 23. Expired inquiry buttons look identical to live ones (7-day false affordance)

`inquiries.py:17`, `views.py:113-114` — buttons persist in Discord forever but
the inquiry expires after 7 days. No visual indication of expiry until the user
taps.

- **Fix**: Improve expiry message:
  `"this option has expired — start a new conversation to revisit."`

### 24. Embed color semantics overlap — blue used for both info content and fork-report exit

`embeds.py:40-44, 96-102` — agent info embeds and "Fork Ended (report)" both
use blue. Glancing at DM history, fork lifecycle events blend into general
content.

- **Fix**: Reserve a distinct color for fork lifecycle events.

---

## LOW — Polish (21 findings)

### 25. Pending updates cap (10) silently drops oldest entries (2x confirmed)

`forks.py:59-61` — `updates[-MAX_PENDING_UPDATES:]` drops oldest entries with no
signal to agent or user.

- **Fix**: When truncation occurs, prepend
  `"(N earlier updates omitted — cap reached)"` to the updates block.
- **Confirmed by**: ux-proactive, ux-continuity

### 26. Denial strikethrough too subtle in subtext

`streamer.py:99` — `-# *~~label~~ — denied*` renders as small italic subtext.
In dontAsk mode the user chose quiet denials, but there's no path to
understanding why something didn't happen.

### 27. 2000-char overflow splits mid-word with no continuation cue

`streamer.py:196-205` — split at exactly char 2000, mid-word/mid-sentence. No
natural break detection, no continuation indicator.

- **Fix**: Attempt to split at last newline or space before the boundary.

### 28. `/permissions` missing trailing period

`bot.py:375` — `"permissions: {mode.value}"` has no trailing period; all other
slash confirmation responses do.

### 29. `max_thinking_tokens` config key uses underscores, peers use dots

`bot.py:410` — choice label is `"max_thinking_tokens"` while peers are
`"model.main"`, `"thinking.fork"` etc.

- **Fix**: Rename to `"thinking.max_tokens"`.

### 30. Permission mode choice labels are camelCase SDK internals

`bot.py:361-366` — `dontAsk`, `acceptEdits`, `bypassPermissions` are not
self-documenting.

- **Fix**: Add short descriptions to parameter `describe()`, or rename to plain
  terms.

### 31. Cancelled approvals leave persistent "cancelled" edits in channel

`permissions.py:159-161` — interrupt calls `cancel_pending()`, all pending
approval messages edit to `"— cancelled"`. Multiple orphaned messages persist.

- **Fix**: Delete rather than edit on cancellation.

### 32. Button handler errors use "Error:" with capital E

`views.py:85, 95, 105` — `f"Error: {e.reason}"` for Google API HttpErrors.
Every other framework message is lowercase.

- **Fix**: `f"failed: {e.reason}"` or just `e.reason`.

### 33. Google API `e.reason` may expose HTTP machinery

`views.py:85` — raw HTTP reason string ("Not Found", "Forbidden") passed through.
User can't tell if retrying makes sense.

- **Fix**: Map known error codes to plain descriptions where actionable.

### 34. `"error: empty response from agent."` unnecessary prefix

`streamer.py:277` — "error:" prefix feels like a system message.

- **Fix**: `"no response — try again."` or remove if unreachable.

### 35. Startup auth message uses bold markdown inconsistent with voice

`main.py:206` — `"**Claude login required**"` — bold header inconsistent with
lowercase one-liner voice.

### 36. Button-triggered fork entry missing `channel.typing()`

`views.py:136-139` — streams directly without typing indicator. Compare
`bot.py:162-163` which explicitly calls `await channel.typing()`.

### 37. `/ping-budget` output "1 critical" unexplained

`ping_budget.py:113-122` — user doesn't know what "critical" means.

- **Fix**: `Critical bypasses: 1 (urgent overrides, not deducted from budget)`.

### 38. Budget status in preamble exposes refill mechanics

`ping_budget.py:99-110` — `"3/5 available (refills 1 every 90 min)"` is
decision-irrelevant noise for the agent. The regret heuristic already drives
correct behavior.

- **Fix**: Simplify to `"budget: 2/5 (next refill in 47 min)"`.

### 39. Chain final-check skips soft escalation option

`preamble.py:380-387` — `"ping the user now"` with no softer intermediate.
Inconsistent with the regret heuristic used elsewhere.

- **Fix**: Add regret clause:
  `"If still unresolved AND the user would regret missing this, ping now."`

### 40. Chain position absent from user-visible pings

`preamble.py:370-388` — agent gets `"check 2 of 4"` but no instruction to
surface it. Pings feel repetitive rather than calibrated.

- **Fix**: Add to chain prompt: "briefly acknowledge the follow-up nature."

### 41. `freely` mode allows ping-without-report (context gap)

`agent_tools.py:408` — stop hook never blocks in `freely` mode. Agent can ping
then stop without calling `report_updates`. Main session gets an alert with no
context.

- **Fix**: Preamble guidance: "if you sent a ping, also call `report_updates`."

### 42. Fork "Open session" description meaningless

`embeds.py:55-60` — no-topic fork entry shows "Open session" which tells the
user nothing about what a fork is or what to do.

- **Fix**: `"branched conversation — changes stay separate from main."`

### 43. Save Context button can fail silently early

`embeds.py:63-86`, `agent.py:257` — clicking Save Context before the fork
produces a session ID returns `"fork discarded (no session to save)"` from a
green "success" button.

### 44. Emoji stripping inconsistent — title only, not field names

`embeds.py:124, 131` — `build_embed()` strips emoji from title but not field
names. Inconsistent policy, not documented.

### 45. `build_embed()` emoji stripping doesn't apply to fork embeds

`embeds.py:55-60, 47-52` — fork embeds bypass `build_embed()`. Currently safe
(hardcoded titles) but a latent inconsistency.

---

## Cross-Domain Patterns

Three patterns emerged from the adversarial review that no single reviewer would
have caught alone:

1. **"Consequential action without context"** — `/thinking` kills forks, stale
   reminders fire late, `/clear` discards forks — all share the pattern of a
   significant action happening without the affected party (user or agent)
   receiving context about the consequences.

2. **"Silent degradation at boundaries"** — reply-to-fork TTL, pending updates
   cap, reconnect greeting, compaction — all involve context crossing a boundary
   where it silently degrades. The system works correctly from a code perspective
   but the user's mental model of "the bot remembers everything" is quietly
   violated.

3. **"Color/formatting as sole differentiator"** — fork exit embeds, denial
   strikethrough, approval timeout messages all rely on subtle visual signals
   (color, subtext size, strikethrough) as the primary UX differentiator. These
   are fragile for an ADHD user where attention to visual detail is unreliable.

---

## Implementation Priority

**Cluster 1 — Error handling (findings #1-3)**: Single PR. Wrap `_dispatch()` in
try/except, add catch-all to `on_app_command_error`, catch CLIConnectionError
for auth recovery. Highest impact, lowest complexity.

**Cluster 2 — Fork lifecycle (findings #4, #6, #16, #17)**: Commands that
drop clients must check fork state first. Fork exit embeds need descriptive
text, not just color.

**Cluster 3 — Context boundaries (findings #5, #7, #15, #19)**: Reply-to-fork
TTL degradation, reconnect greeting, pending updates visibility. Each is
independent but shares the "silent degradation" pattern.

**Cluster 4 — Proactive outreach (findings #8, #13, #14)**: Bg fork failure
messages, stale reminder context, reminder creation confirmation. Mostly prompt
and message string changes.

**Cluster 5 — Button/embed polish (findings #20-24)**: Dismiss label, button
count limit, inquiry race, expired button affordance, color semantics. Mixed
complexity.
