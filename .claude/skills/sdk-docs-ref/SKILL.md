---
name: sdk-docs-ref
description: "Preload SDK reference only: Python API surface + doc indexes for all three sites. Use as a lightweight context primer before SDK work."
disable-model-invocation: true
allowed-tools: Bash(curl *)
---

# SDK docs — reference only

Preload the Python SDK API reference and all three doc indexes for on-demand lookup.

## Doc indexes

ollim-bot:
!`curl -s https://docs.ollim.ai/llms.txt`

Agent SDK:
!`curl -s https://platform.claude.com/llms.txt | grep agent-sdk`

Claude Code:
!`curl -s https://code.claude.com/docs/llms.txt`

## Python SDK reference

!`curl -s https://platform.claude.com/docs/en/agent-sdk/python.md`
