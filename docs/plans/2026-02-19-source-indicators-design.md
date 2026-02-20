# Source Indicators for Ping/Embed Tools + Bg Fork Stop Guard

## Problem

When the agent sends messages via `ping_user` or `discord_embed`, the recipient has
no way to tell whether the message came from the main session, a background fork, or
an interactive fork. Additionally, bg forks can send visible output and then stop
without calling `report_updates`, leaving the main session unaware of what happened.

## Source Indicators

### `ping_user`

- **Main session**: return error (agent output already visible in conversation)
- **Interactive fork**: return error (user sees the stream)
- **Bg fork**: allowed, message prefixed with `[bg] `

### `discord_embed`

- **Main session**: no footer (default context, no label needed)
- **Interactive fork**: footer text `"fork"`
- **Bg fork**: footer text `"bg"`

## Bg Fork Stop Guard

### State tracking

- New contextvar `_bg_output_sent: ContextVar[bool]` (default `False`)
- `ping_user` / `discord_embed`: set flag to `True` when `in_bg_fork()`
- `report_updates`: set flag to `False`

### Stop hook

- Registered in `Agent.__init__` via `ClaudeAgentOptions.hooks`
- No-op for non-bg-fork sessions (`in_bg_fork()` gates the check)
- When `in_bg_fork() and _bg_output_sent.get()`: inject `systemMessage` telling the
  agent to call `report_updates` before stopping
- Bg fork clients inherit the hook automatically via shared `self.options`

## Scope

~15 lines total across `agent_tools.py` and `agent.py`.
