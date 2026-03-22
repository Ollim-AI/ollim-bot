---
name: sdk-docs-ref
description: "Preload SDK reference only: Python API surface + doc indexes for all three sites. Use as a lightweight context primer before SDK work."
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

# Important Read Step - DO NOT SKIP
Always Read the complete Python SDK Reference before doing work on any SDK related task!
