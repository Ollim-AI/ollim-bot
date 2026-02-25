# Bot Debugger Memory

## Investigation Patterns

### Ping Budget Investigation (2026-02-23)
- Session search IDs from `claude-history search` are **prompt UUIDs**, not session IDs. Use `response <uuid>` to read them, not `transcript`.
- Budget status is in BG_PREAMBLE: search for `"remaining today"` in prompts to trace consumption over time.
- `Embed sent.` and `Message sent.` are tool result strings -- `-vvv` shows them, but search may not find them since they're in result blocks.
- Key finding: 19 bg routines all with `allow_ping: true`, many sending multiple embeds per routine. Budget of 15 is structurally insufficient.

### Session ID vs Prompt UUID
- `claude-history sessions` returns session IDs (use with `transcript`)
- `claude-history search` returns prompt UUIDs (use with `response` or `prompts`)
- If `transcript <id>` says "No session found", try `response <id>` instead

### Thinking Blocks Not Stored (2026-02-23)
- Claude Code SDK **does not persist thinking blocks** to session JSONL files
- `"type":"thinking"` appears zero times across all ~150 JSONL files in the project
- `-vv` on claude-history shows no `[thinking]` sections because there are none to show
- The agent's reasoning is only visible through its **text output** (intermediate reasoning text blocks before tool calls)
- With `max_thinking_tokens=10000` set, thinking happens but is ephemeral -- never written to disk
- To understand the agent's decision-making, read its text output at `-v` or `-vv` verbosity

### Compaction Event Logging Bug (2026-02-24)
- `save_session_id()` detects compaction by checking if session ID changed (`current != session_id`)
- **Bug: SDK does not change session ID on compaction.** It creates a new context window within the same session.
- Evidence: session `65e89751` has 3 context windows across 2 compactions, same ID throughout
- `ResultMessage.session_id` after `/compact` equals the pre-compaction ID, so `save_session_id` sees no change
- The `compact_boundary` SystemMessage has no new session ID either -- `sessionId` field stays the same
- Fix needed: detect compaction via `SystemMessage.subtype == "compact_boundary"` instead of session ID comparison
- Note: the first compaction (Feb 18) went from session `3906f8d0` to `65e89751` (different IDs, different JSONL files). This may have been a different SDK version or behavior. But the Feb 24 compaction kept the same ID.

## Useful Search Queries
- `"remaining today"` in prompts (-p) -- traces budget consumption across bg forks
- `"Embed sent"` or `"Budget exhausted"` in responses (-r) -- finds successful/blocked pings
- `"routine-bg:"` in prompts -- finds bg routine sessions
- `"discord_embed"` in responses -- finds all embed tool calls
- `"would the user regret"` -- finds sessions with new regret-based preamble (deployed 94d7a9e)
- `"Plan pings carefully"` -- finds sessions with old preamble (pre-94d7a9e)
- `"let me be strategic"` or `"budget is"` -- finds agent reasoning about budget in text output
