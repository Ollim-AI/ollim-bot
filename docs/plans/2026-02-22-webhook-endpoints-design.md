# Webhook Endpoints: External Triggers via HTTP

HTTP endpoint that triggers agent bg forks from external services (CI/CD,
GitHub, phone notification relay, IFTTT/Zapier). Fire-and-forget: caller gets
202 Accepted, agent reports results via Discord.

## Decisions

- **Scope**: `/hook/agent` only (bg fork). No main-session injection (`/hook/wake`).
- **Framework**: aiohttp — asyncio-native, embeds in Discord.py's event loop.
- **Auth**: Bearer token from `WEBHOOK_SECRET` env var, constant-time comparison.
- **Response**: 202 Accepted, fire-and-forget. No job IDs, no status polling.
- **Lifecycle**: Opt-in via `WEBHOOK_PORT` env var. Refuses to start without
  `WEBHOOK_SECRET` (fail fast, not silent insecurity).

## Payload

```json
POST /hook/agent
Authorization: Bearer <WEBHOOK_SECRET>
Content-Type: application/json

{
  "message": "CI build failed for ollim-bot#42",
  "source": "github-actions",
  "isolated": true,
  "model": "haiku",
  "thinking": true,
  "allow_ping": true,
  "update_main_session": "on_ping"
}
```

- `message` (str): required — the prompt injected into the bg fork
- `source` (str): optional, default `"webhook"` — used in prompt tag and agent
  provenance context
- `isolated` (bool): optional, default `false` — `true` creates standalone
  client with no conversation history
- `model` (str): optional — model override (`"haiku"`, `"sonnet"`, `"opus"`)
- `thinking` (bool): optional, default `true` — extended thinking toggle
- `allow_ping` (bool): optional, default `true` — controls ping_user/discord_embed
  availability
- `update_main_session` (str): optional, default `"on_ping"` — one of
  `always`, `on_ping`, `freely`, `blocked`

## Module: `src/ollim_bot/webhook.py`

Single module owns all HTTP concerns. No sub-package (one endpoint, one handler).

### Startup

`bot.py:on_ready` calls `webhook.start(agent, owner)` after scheduler setup.
No-op if `WEBHOOK_PORT` unset. Logs error and returns if `WEBHOOK_SECRET`
missing (fail fast).

```python
_runner: web.AppRunner | None = None

async def start(agent: Agent, owner: discord.User) -> None:
    port = os.environ.get("WEBHOOK_PORT")
    secret = os.environ.get("WEBHOOK_SECRET")
    if not port:
        return
    if not secret:
        log.error("WEBHOOK_PORT set but WEBHOOK_SECRET missing")
        return
    app = web.Application()
    app.router.add_post("/hook/agent", _handle_agent)
    # store agent, owner, secret on app for handler access
    ...
    # bind 127.0.0.1 only (WSL2 mirrored networking)
    site = web.TCPSite(runner, "127.0.0.1", int(port))
    await site.start()

async def stop() -> None:
    if _runner:
        await _runner.cleanup()
```

### Request parsing

Parse into frozen dataclass at the HTTP boundary:

```python
@dataclass(frozen=True, slots=True)
class WebhookRequest:
    message: str
    source: str = "webhook"
    isolated: bool = False
    model: str | None = None
    thinking: bool = True
    allow_ping: bool = True
    update_main_session: str = "on_ping"
```

Validation: reject 400 if `message` missing, `update_main_session` not in
valid set, or body isn't valid JSON. Auth checked first (401 before body parse).

### Handler

```python
async def _handle_agent(request: web.Request) -> web.Response:
    # 1. Auth check (constant-time via hmac.compare_digest)
    # 2. Parse JSON body into WebhookRequest
    # 3. Build prompt: [webhook:<source>] <bg_preamble> <message>
    # 4. asyncio.create_task(run_agent_background(...))
    # 5. Return 202 Accepted
```

### Prompt construction

Tag: `[webhook:<source>]` — follows existing `[routine-bg:X]` / `[reminder-bg:X]`
convention. Reuses `_build_bg_preamble()` from `scheduling/scheduler.py`.

```
[webhook:github-actions] Your text output will be discarded. Use `ping_user`...

CI build failed for ollim-bot#42
```

## Concurrency

Identical to scheduler bg forks:

- `asyncio.create_task(run_agent_background(...))` — fire-and-forget, no lock
- Contextvars set before client creation (via `run_agent_background` internals)
- Ping budget applies (same enforcement path)
- Busy-awareness applies (non-critical pings blocked when main session locked)
- No new concurrency primitives needed

## Error responses

| Condition | Status | Body |
|-----------|--------|------|
| Missing/invalid auth | 401 | `{"error": "unauthorized"}` |
| Invalid JSON body | 400 | `{"error": "invalid json"}` |
| Missing `message` | 400 | `{"error": "message required"}` |
| Invalid `update_main_session` | 400 | `{"error": "invalid update_main_session: ..."}` |
| Success | 202 | `{"status": "accepted"}` |

Bg fork failures handled by `run_agent_background`'s existing error path
(timeout notification, error logging). HTTP caller already got 202.

## Changes to existing files

- `bot.py`: import `webhook`, call `webhook.start(agent, owner)` in `on_ready`
  after scheduler, call `webhook.stop()` in cleanup
- `config.py`: no change — webhook env vars are optional, read directly in
  `webhook.py` via `os.environ.get()`
- `scheduling/scheduler.py`: export `_build_bg_preamble` (rename to
  `build_bg_preamble`, drop leading underscore)
- `pyproject.toml`: add `aiohttp` dependency
- `CLAUDE.md`: add webhook section documenting the new module

## YAGNI

Not included (revisit when use cases emerge):

- `/hook/wake` (main session injection)
- Job ID / status polling
- Rate limiting
- OpenAPI docs
- Webhook registration / dynamic endpoints
