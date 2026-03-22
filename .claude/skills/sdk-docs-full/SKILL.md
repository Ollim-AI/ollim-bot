---
name: sdk-docs-full
description: "Preload complete SDK context: reference, core docs, streaming, MCP, subagents, system prompts, Claude Code features, and ollim-bot architecture. Use before major SDK refactors or deep audits."
disable-model-invocation: true
allowed-tools: Bash(curl *)
---

# SDK docs — full context

Preload everything needed for deep SDK work on ollim-bot. Ordered by usefulness.

## Doc indexes

ollim-bot:
!`curl -s https://docs.ollim.ai/llms.txt`

Agent SDK:
!`curl -s https://platform.claude.com/llms.txt | grep agent-sdk`

Claude Code:
!`curl -s https://code.claude.com/docs/llms.txt`

## S-tier — ground truth

### Python SDK reference
!`curl -s https://platform.claude.com/docs/en/agent-sdk/python.md`

## A-tier — directly informs correct SDK usage

### Agent loop (compaction, turns, message types, context window)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/agent-loop.md`

### Hooks (callback signatures, matcher semantics, hook output)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/hooks.md`

### Permissions (evaluation flow, modes, allow/deny rules)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/permissions.md`

### Sessions (resume, fork, continue semantics)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/sessions.md`

## B-tier — helpful background

### Streaming output (StreamEvent, partial messages, text/tool streaming)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/streaming-output.md`

### MCP (server types, tool naming, tool search, auth)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/mcp.md`

### Custom tools (@tool decorator, create_sdk_mcp_server, streaming input requirement)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/custom-tools.md`

### Subagents (AgentDefinition, context isolation, tool restrictions)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/subagents.md`

### System prompts (CLAUDE.md, presets, append, setting_sources)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/modifying-system-prompts.md`

### Claude Code features (settingSources, skills, hooks from filesystem)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/claude-code-features.md`

### Streaming input (async generator vs single message, ClaudeSDKClient)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/streaming-vs-single-mode.md`

### User input (canUseTool callback, AskUserQuestion)
!`curl -s https://platform.claude.com/docs/en/agent-sdk/user-input.md`

## ollim-bot architecture (how the bot uses the SDK)

### How ollim-bot works
!`curl -s https://docs.ollim.ai/architecture/how-it-works.md`

### Context flow
!`curl -s https://docs.ollim.ai/architecture/context-flow.md`

### Session management
!`curl -s https://docs.ollim.ai/architecture/session-management.md`
