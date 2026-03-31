---
name: e2e-docker-test
description: End-to-end test ollim-bot in Docker. Use when verifying containerized deployment, testing model backends, or validating session persistence.
argument-hint: <ollama|claude> [model-name]
allowed-tools: Bash(docker *), Bash(rm *), Read
disable-model-invocation: true
---

# E2E Docker Test

Verify ollim-bot works in a container with a real model backend.

## Setup

```bash
docker compose build ollim-bot
docker compose up -d ollama
# Wait for healthy (entrypoint auto-pulls the model)
```

## Test matrix

Run each applicable path. The entrypoint handles model pulling automatically.

### Ollama path

```bash
printf 'Say exactly: PONG\n' | docker compose run --rm -T \
  -e OLLIM_USER_NAME=TestUser -e OLLIM_BOT_NAME=TestBot \
  -e ANTHROPIC_AUTH_TOKEN=skip \
  -e ANTHROPIC_BASE_URL=http://ollama:11434 \
  -e ANTHROPIC_MODEL=<model> -e ANTHROPIC_SMALL_FAST_MODEL=<model> \
  ollim-bot uv run --no-dev ollim-bot chat --model <model>
```

### Claude path

```bash
printf 'Say exactly: PONG\n' | docker compose run --rm -T \
  -v "$HOME/.claude:/home/bot/.claude:rw" \
  -e OLLIM_USER_NAME=TestUser -e OLLIM_BOT_NAME=TestBot \
  ollim-bot uv run --no-dev ollim-bot chat --model haiku
```

### Auth failure path

```bash
docker compose run --rm -T \
  -e OLLIM_USER_NAME=TestUser -e OLLIM_BOT_NAME=TestBot \
  ollim-bot uv run --no-dev ollim-bot chat
# Expect: "not logged in to claude" + exit 1
```

## Session persistence test (BANANA test)

Two-run test that proves session transcript replay works — not filesystem bypass.

**Run 1:** Set the secret word.
```bash
printf 'The secret word is BANANA. Do not write it to any file. Just remember it.\n' | docker compose run --rm -T <env-vars> ollim-bot uv run --no-dev ollim-bot chat --model <model>
```

**Run 2:** Recall it.
```bash
printf 'What is the secret word?\n' | docker compose run --rm -T <env-vars> ollim-bot uv run --no-dev ollim-bot chat --model <model>
```

**Verify:** Response contains "BANANA". Then confirm no filesystem bypass:
```bash
docker compose run --rm -T <env-vars> ollim-bot \
  find /home/bot/.claude/projects -name "*.md" -path "*/memory/*"
# Expect: empty (no memory files written)
```

### Known limitation

Session resume fails with small models (qwen3.5:2b) — the system prompt (~25k tokens) fills the context window, so the CLI auto-compacts conversation history away. Use Claude or a large-context model for this test.

## Cleanup

```bash
docker compose down -v
rm -rf "$HOME/.claude/projects/-home-bot--ollim-bot"  # only if Claude path was tested
```
