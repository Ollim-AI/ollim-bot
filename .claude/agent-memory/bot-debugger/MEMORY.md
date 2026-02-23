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

## Useful Search Queries
- `"remaining today"` in prompts (-p) -- traces budget consumption across bg forks
- `"Embed sent"` or `"Budget exhausted"` in responses (-r) -- finds successful/blocked pings
- `"routine-bg:"` in prompts -- finds bg routine sessions
- `"discord_embed"` in responses -- finds all embed tool calls
