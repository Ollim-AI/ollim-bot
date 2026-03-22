---
name: sdk-docs-core
description: "Preload SDK reference + most useful docs: Python API, agent loop, hooks, permissions, sessions. Use before auditing SDK usage or fixing SDK-related bugs."
disable-model-invocation: true
allowed-tools: Bash(curl *)
---

# SDK docs — reference + core

Preload the Python SDK reference plus the docs that directly inform correct SDK usage for ollim-bot.

## Doc indexes

ollim-bot:
!`curl -s https://docs.ollim.ai/llms.txt`

Agent SDK:
!`curl -s https://platform.claude.com/llms.txt | grep agent-sdk`

Claude Code:
!`curl -s https://code.claude.com/docs/llms.txt`

## Python SDK reference (S-tier — the ground truth for all API patterns)

!`curl -s https://platform.claude.com/docs/en/agent-sdk/python.md`

## Agent loop (A-tier — compaction, turns, message types, context window)

!`curl -s https://platform.claude.com/docs/en/agent-sdk/agent-loop.md`

## Hooks (A-tier — callback signatures, matcher semantics, hook output)

!`curl -s https://platform.claude.com/docs/en/agent-sdk/hooks.md`

## Permissions (A-tier — evaluation flow, modes, allow/deny rules)

!`curl -s https://platform.claude.com/docs/en/agent-sdk/permissions.md`

## Sessions (A-tier — resume, fork, continue semantics)

!`curl -s https://platform.claude.com/docs/en/agent-sdk/sessions.md`
