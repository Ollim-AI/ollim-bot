# Design: bg fork button → interactive fork resume

## Problem

Agent buttons on bg routine embeds route inquiries to the main session. The user loses
the bg fork's context — the agent doesn't know what routine it ran or what it found.

Reply-to-fork exists to bridge this gap, but the user reports it starts a fork with the
wrong session (main session context, not bg fork context).

## Goal

Clicking an agent button on a bg fork embed opens an interactive fork that resumes from
the bg fork's session, so the agent has full context of what it did.

## Approach: Route existing agent buttons through bg fork session

No new button types. Existing `agent:` buttons on bg embeds automatically route smarter
based on whether the message has a tracked fork session.

## Design

### 1. `_handle_agent_inquiry` routing (`views.py`)

After popping the inquiry prompt, check `lookup_fork_session(interaction.message.id)`.

Three branches:

- **No session tracked** → existing behavior: route `[button] {prompt}` to main session
- **Session found, no active fork** → enter interactive fork resuming from that session,
  send the fork-enter embed, dispatch the inquiry into the fork
- **Session found, fork already active** → ephemeral "already in a fork" message

Channel-sync invariant maintained: both `set_channel` and `permissions.set_channel`
called before dispatching.

### 2. Fork entry prompt for bg-resume forks (`bot.py`)

A new prompt variant distinct from `_fork_topic_prompt` and `_FORK_NO_TOPIC_PROMPT`:

```
[fork-started] You are in an interactive fork continuing from the background routine
you just ran. {USER_NAME} clicked a button in response to your output.
Button action: {prompt}

Respond to their action.
```

No exit-options instruction — user exits via buttons on the fork-enter embed.

This is passed to `stream_chat` as the first message after `enter_interactive_fork`,
same as the `/fork` command path.

### 3. Reply-to-fork "wrong session" investigation

**Symptom**: Reply to a bg fork message starts a fork with main session context,
not bg fork context.

**Likely cause**: `lookup_fork_session` returns `None` (message not tracked) → quoted
context is prepended → main session processes it → agent autonomously calls `enter_fork`
MCP tool → fork starts from main session.

**Investigation during implementation**:
- After a bg routine fires, check `~/.ollim-bot/fork_messages.json` to confirm message
  IDs are tracked and session IDs are correct.
- Verify whether `--resume <bg_fork_session_id> --fork-session` loads bg context or
  starts fresh.

**Fallback fix if bg fork sessions aren't resumable**:
In `create_forked_client`, when `session_id` refers to a bg fork session, use
`resume=session_id` without `fork_session=True` — continue the session directly rather
than forking from it. This still gives the agent full bg context. The tradeoff: the
interactive fork continues the bg session's history rather than branching it, so
`save_context` would promote a session that has bg-mode turns in it.

## Files changed

- `src/ollim_bot/views.py` — `_handle_agent_inquiry`: add fork session lookup and
  routing; add new `_enter_fork_from_bg` helper (or inline)
- `src/ollim_bot/bot.py` — add `_fork_bg_resume_prompt(prompt)` function; expose it
  for use in views.py (or pass agent reference)
- `src/ollim_bot/sessions.py` — no changes needed; `lookup_fork_session` already works
- `src/ollim_bot/agent.py` — possibly: add `enter_interactive_fork` overload that
  doesn't use `fork_session=True`

## Not in scope

- New button types
- Agent changes (no new tool instructions)
- Multi-tenancy or auth
