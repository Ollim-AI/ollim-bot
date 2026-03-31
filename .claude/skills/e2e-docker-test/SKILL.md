---
name: e2e-docker-test
description: Spin up ollim-bot in Docker with a real model backend, run tests, clean up. Use when verifying behavior in a containerized environment.
argument-hint: <what to test> [--model ollama:qwen3.5:2b | claude:haiku]
allowed-tools: Bash(docker *), Bash(rm *), Bash(printf *), Read
disable-model-invocation: true
---

# E2E Docker Test

Spin up the bot in Docker, test what the user asked, tear down.

## 1. Start the environment

```bash
docker compose build ollim-bot
docker compose up -d ollama
# Wait for healthy
for i in $(seq 1 12); do
  docker compose ps --format "{{.Status}}" ollama 2>/dev/null | grep -q "healthy" && break
  sleep 5
done
```

## 2. Send messages

Parse the model from the argument (default: `claude:haiku`). The entrypoint auto-pulls Ollama models.

**Ollama:**
```bash
printf '<message>\n' | docker compose run --rm -T \
  -e OLLIM_USER_NAME=TestUser -e OLLIM_BOT_NAME=TestBot \
  -e ANTHROPIC_AUTH_TOKEN=skip \
  -e ANTHROPIC_BASE_URL=http://ollama:11434 \
  -e ANTHROPIC_MODEL=<model> -e ANTHROPIC_SMALL_FAST_MODEL=<model> \
  ollim-bot uv run --no-dev ollim-bot chat --model <model>
```

**Claude:**
```bash
printf '<message>\n' | docker compose run --rm -T \
  -v "$HOME/.claude:/home/bot/.claude:rw" \
  -e OLLIM_USER_NAME=TestUser -e OLLIM_BOT_NAME=TestBot \
  ollim-bot uv run --no-dev ollim-bot chat --model <model>
```

Send as many messages as the test requires. Each `docker compose run` is a separate session but resumes the previous conversation (session state persists in volumes).

## 3. Clean up

Always run cleanup when testing is done:

```bash
docker compose down -v
rm -rf "$HOME/.claude/projects/-home-bot--ollim-bot"  # Claude path only
```

## Gotchas

- **Session resume fails with small models** — system prompt (~25k tokens) fills the context window. Use Claude or large-context models for multi-run tests.
- **Switching between Ollama and Claude** requires `docker compose down -v` first (incompatible session state).
