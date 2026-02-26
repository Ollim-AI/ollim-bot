# ollim-bot Documentation Site Specification

Spec for a documentation site modeled after [code.claude.com/docs](https://code.claude.com/docs/en/overview).
Replicates the site **structure, navigation patterns, and UI components** — not the content.

## Reference Site Analysis

The Claude Code docs site has **57 pages** across ~12 sections, built with **Mintlify** (MDX + YAML frontmatter).
Key structural patterns:

- Flat URL structure (`/en/<slug>`) with sidebar grouping
- Pages follow distinct templates: overview, tutorial, feature guide, reference, integration guide, policy
- Heavy use of MDX components: `<Tabs>`, `<Steps>`, `<CardGroup>`, `<Accordion>`, `<Note>`, `<Tip>`, `<Warning>`
- Cross-linking hub pages that act as decision matrices
- `llms.txt` machine-readable index for AI consumption
- Consistent page anatomy: H1 + subtitle, intro, main content (H2/H3), "Next steps" card group

---

## Framework Choice

**Mintlify** — matches the reference site exactly, minimal config, built-in components.

Alternatives considered:
| Framework | Pros | Cons |
|-----------|------|------|
| **Mintlify** | Identical component set, hosted, `llms.txt` built-in | Paid (free tier may suffice), vendor-hosted |
| **Nextra** (Next.js) | Free, self-hostable, MDX native | Must build/style components manually |
| **Starlight** (Astro) | Fast, free, good sidebar system | Different component ecosystem |
| **Docusaurus** | Mature, free, plugin ecosystem | Heavier, React-based, MDX v2 quirks |
| **VitePress** | Fast, Vue-based, clean defaults | Vue ecosystem (project is Python) |

Decision deferred — spec is framework-agnostic (MDX notation used for component examples).

---

## Site Map

### Section 1: Getting Started
| Slug | Title | Page Type | Description |
|------|-------|-----------|-------------|
| `overview` | ollim-bot overview | Landing/overview | What it is, who it's for, key capabilities, surface overview (Discord DMs, slash commands, scheduled tasks) |
| `quickstart` | Quickstart | Tutorial | Clone, configure `.env`, `uv sync`, `uv run ollim-bot` — first message in <5 min |
| `setup` | Setup guide | Setup guide | Full setup: Discord bot creation, Google OAuth, data directory, env vars, first run |
| `how-it-works` | How ollim-bot works | Conceptual guide | Agent loop, session persistence, fork model, context flow diagram |
| `design-philosophy` | Design philosophy | Conceptual guide | Adapted from existing `docs/design-philosophy.md` |

### Section 2: Core Usage
| Slug | Title | Page Type | Description |
|------|-------|-----------|-------------|
| `conversations` | Conversations | Feature guide | DM interface, @mentions, message flow, interrupt-on-new-message, context management |
| `slash-commands` | Slash commands | Reference | All Discord slash commands: `/clear`, `/compact`, `/cost`, `/model`, `/thinking`, `/fork`, `/interrupt`, `/permissions`, `/ping-budget` |
| `forks` | Forks | Feature guide | Interactive forks, background forks, exit strategies (save/report/discard), idle timeout |
| `embeds-and-buttons` | Embeds & buttons | Feature guide | How the agent sends embeds, button actions, inquiry flow, persistent buttons |
| `permissions` | Permissions | Reference/guide | Permission modes (`dontAsk`, `default`, `acceptEdits`, `bypassPermissions`), approval flow, session-allowed set |

### Section 3: Scheduling
| Slug | Title | Page Type | Description |
|------|-------|-----------|-------------|
| `scheduling-overview` | Scheduling overview | Overview | How proactive scheduling works, routines vs reminders, scheduler polling |
| `routines` | Routines | Feature guide | Recurring crons, YAML frontmatter spec, markdown body, file format, examples |
| `reminders` | Reminders | Feature guide | One-shot + chainable, YAML frontmatter spec, `max_chain`, follow-up chains |
| `background-forks` | Background forks | Feature guide | How bg forks work, `isolated` mode, model overrides, thinking overrides, tool restrictions, `update_main_session` modes, `allow_ping`, ping budget awareness |
| `ping-budget` | Ping budget | Feature guide | Refill-on-read bucket, capacity, refill rate, critical bypass, daily counters, `/ping-budget` command |

### Section 4: Integrations
| Slug | Title | Page Type | Description |
|------|-------|-----------|-------------|
| `google-overview` | Google integration | Overview | OAuth setup, shared auth, available services |
| `google-tasks` | Google Tasks | Integration guide | Task management, CLI commands, embed buttons, complete/delete actions |
| `google-calendar` | Google Calendar | Integration guide | Event management, CLI commands, embed buttons, delete actions |
| `google-gmail` | Gmail | Integration guide | Read-only access, gmail-reader subagent, email triage patterns |
| `webhooks` | Webhooks | Integration guide | External triggers, webhook spec files, YAML schema, auth, payload validation, Haiku screening, dispatch |

### Section 5: Extending ollim-bot
| Slug | Title | Page Type | Description |
|------|-------|-----------|-------------|
| `extending-overview` | Extend ollim-bot | Overview/decision guide | Decision matrix: when to use routines vs reminders vs webhooks vs MCP tools vs subagents |
| `mcp-tools` | MCP tools | Reference | All MCP tools: `discord_embed`, `ping_user`, `follow_up_chain`, `save_context`, `report_updates`, `enter_fork`, `exit_fork` |
| `subagents` | Subagents | Feature guide | gmail-reader, history-reviewer, responsiveness-reviewer — what they do, how they're defined |
| `system-prompt` | System prompt | Reference | How the system prompt is structured, what's injected (tool instructions, pending updates, bg preamble) |
| `adding-integrations` | Adding new integrations | Developer guide | How to add a new Google service, new MCP tool, new CLI command, new webhook spec |

### Section 6: Configuration
| Slug | Title | Page Type | Description |
|------|-------|-----------|-------------|
| `configuration` | Configuration reference | Reference | All env vars, `.env` file, data directory structure, file formats |
| `data-directory` | Data directory | Reference | `~/.ollim-bot/` layout: routines, reminders, webhooks, sessions, pending updates, credentials, etc. |
| `file-formats` | File formats | Reference | YAML frontmatter specs for routines, reminders, webhooks; JSONL formats for session history, pending updates |

### Section 7: Architecture
| Slug | Title | Page Type | Description |
|------|-------|-----------|-------------|
| `architecture` | Architecture overview | Conceptual guide | Module map, dependency diagram, data flow |
| `session-management` | Session management | Feature guide | Persistent sessions, session history JSONL, compaction, `/clear` lifecycle |
| `context-flow` | Context flow | Conceptual guide | How context flows: main session → forks → bg forks → pending updates → back to main |
| `streaming` | Streaming & Discord | Feature guide | How agent responses stream to Discord, throttled edits, 2000-char overflow, typing indicators |

### Section 8: Development
| Slug | Title | Page Type | Description |
|------|-------|-----------|-------------|
| `development` | Development guide | Developer guide | Dev setup, running locally, project structure, code conventions |
| `testing` | Testing | Developer guide | Test philosophy, running tests, no mocks policy |
| `cli-reference` | CLI reference | Reference | `ollim-bot` subcommands: bot, routine, reminder, tasks, cal, gmail |
| `troubleshooting` | Troubleshooting | Support/reference | Common issues, debugging, log locations, session recovery |

### Section 9: Self-Hosting
| Slug | Title | Page Type | Description |
|------|-------|-----------|-------------|
| `self-hosting` | Self-hosting guide | Setup guide | Running your own instance, forking the repo, what to customize |
| `discord-bot-setup` | Discord bot setup | Tutorial | Step-by-step: create Discord application, bot token, intents, invite link |
| `google-oauth-setup` | Google OAuth setup | Tutorial | Step-by-step: Google Cloud Console, credentials.json, first auth flow |

### Section 10: Reference
| Slug | Title | Page Type | Description |
|------|-------|-----------|-------------|
| `changelog` | Changelog | Changelog | Version history, links to git log or CHANGELOG.md |

**Total: ~37 pages** across 10 sections.

---

## UI Components Spec

Components to replicate from the reference site, with ollim-bot usage examples.

### Navigation & Layout
| Component | Behavior | Usage |
|-----------|----------|-------|
| **Sidebar** | Grouped nav links by section, collapsible groups, active page highlight | Site-wide |
| **Search** | Full-text search across all pages | Site-wide |
| **Dark/light mode** | Theme toggle, respects system preference | Site-wide |
| **Mobile responsive** | Hamburger menu, collapsible sidebar | Site-wide |

### Content Components
| Component | Syntax | Usage |
|-----------|--------|-------|
| **Tabs** | `<Tabs><Tab title="...">` | Switching between: routine vs reminder examples, interactive vs background fork, CLI vs Discord usage |
| **Steps** | `<Steps><Step title="...">` | Setup tutorials, OAuth flow, webhook creation |
| **Accordion** | `<AccordionGroup><Accordion title="...">` | FAQ sections, expandable examples, YAML field descriptions |
| **Card Group** | `<CardGroup><Card title="..." icon="..." href="...">` | "Next steps" navigation at page bottoms, feature overviews |
| **Code Blocks** | ` ```yaml `, ` ```python `, ` ```bash ` | YAML frontmatter examples, Python snippets, CLI commands |
| **Tables** | Standard markdown tables | Config reference, env vars, slash command flags, comparison matrices |

### Admonitions
| Component | Color | Usage |
|-----------|-------|-------|
| **Note** | Blue | Important context, "this applies to bg forks only" |
| **Tip** | Green | Best practices, "use `isolated: true` for email triage" |
| **Warning** | Orange | Gotchas, "channel-sync invariant — every `stream_chat` path needs both calls" |
| **Info** | Light blue | Background context, "the scheduler polls every 10s" |

### Media
| Component | Usage |
|-----------|-------|
| **SVG/Mermaid diagrams** | Architecture overview, context flow, fork lifecycle, agent loop |
| **Screenshots** | Discord DM interface, embed examples, button interactions, slash command usage |
| **Dark/light image pairs** | Diagrams that need theme-appropriate colors |

### Special Components
| Component | Usage |
|-----------|-------|
| **Decision matrix table** | `extending-overview`: when to use routines vs reminders vs webhooks vs subagents |
| **YAML frontmatter examples** | Routine/reminder/webhook spec files shown as annotated code blocks |
| **`llms.txt` index** | Machine-readable page list for AI agent consumption |

---

## Page Templates

### Template: Overview/Landing
```
# {Title}
> {One-line subtitle}

{2-3 paragraph introduction}

## Key features
<CardGroup cols={3}>
  <Card title="..." icon="..." href="...">...</Card>
  ...
</CardGroup>

## How it works
{Brief conceptual explanation with diagram}

## Next steps
<CardGroup cols={2}>
  <Card title="..." href="...">...</Card>
  ...
</CardGroup>
```

### Template: Feature Guide
```
# {Title}
> {One-line subtitle}

{Introduction paragraph}

## Overview
{What this feature does and why}

## {Core concept 1}
{Explanation + code examples}

<Note>{Important caveat}</Note>

## {Core concept 2}
<Tabs>
  <Tab title="...">...</Tab>
  <Tab title="...">...</Tab>
</Tabs>

## Configuration
{YAML/env var reference table}

## Examples
{Practical usage examples}

## Next steps
<CardGroup>...</CardGroup>
```

### Template: Tutorial
```
# {Title}
> {One-line subtitle}

## Prerequisites
- {Requirement 1}
- {Requirement 2}

<Steps>
  <Step title="...">
    {Instructions + code block}
  </Step>
  <Step title="...">
    {Instructions + code block}
  </Step>
</Steps>

<Tip>{What to try next}</Tip>

## Next steps
<CardGroup>...</CardGroup>
```

### Template: Reference
```
# {Title}
> {One-line subtitle}

{Brief intro paragraph}

## {Category 1}
| Flag/Field | Type | Default | Description |
|------------|------|---------|-------------|
| ... | ... | ... | ... |

## {Category 2}
| ... |

## Examples
```yaml
...
```
```

### Template: Integration Guide
```
# {Title}
> {One-line subtitle}

{What this integration does}

## Prerequisites
- {Requirement}

## Setup
<Steps>...</Steps>

## Usage
{How to use once set up}

<Tabs>
  <Tab title="CLI">{CLI examples}</Tab>
  <Tab title="Agent">{How the agent uses it}</Tab>
</Tabs>

## Troubleshooting
<AccordionGroup>
  <Accordion title="...">...</Accordion>
</AccordionGroup>
```

---

## Content Priority

Recommended authoring order (highest value first):

### Phase 1 — Core (get people running)
1. `overview` — what is this, who is it for
2. `quickstart` — running in <5 min
3. `setup` — full setup guide
4. `discord-bot-setup` — Discord application creation
5. `google-oauth-setup` — Google credentials

### Phase 2 — Usage (daily reference)
6. `conversations` — how to talk to the bot
7. `slash-commands` — command reference
8. `routines` — recurring schedules
9. `reminders` — one-shot + chains
10. `forks` — conversation branching

### Phase 3 — Depth (power users)
11. `how-it-works` — conceptual model
12. `design-philosophy` — (already written)
13. `background-forks` — bg fork config
14. `webhooks` — external triggers
15. `mcp-tools` — tool reference
16. `configuration` — env vars + data dir

### Phase 4 — Developer (contributors/forkers)
17. `architecture` — module map
18. `development` — dev setup
19. `cli-reference` — CLI subcommands
20. `adding-integrations` — extending the bot
21-37. Remaining pages

---

## Feature Checklist

### Must-Have (matches reference site)
- [ ] Sidebar navigation with section grouping
- [ ] Full-text search
- [ ] Dark/light mode
- [ ] Mobile responsive layout
- [ ] MDX with component library (Tabs, Steps, Cards, Accordions, Admonitions)
- [ ] Syntax-highlighted code blocks (YAML, Python, bash, JSON)
- [ ] `llms.txt` machine-readable index
- [ ] "Next steps" card groups on every page
- [ ] SEO metadata (title, description per page)

### Nice-to-Have
- [ ] Version selector (if ollim-bot releases versioned docs)
- [ ] Copy button on code blocks
- [ ] Table of contents sidebar (per-page)
- [ ] Edit on GitHub link per page
- [ ] OpenGraph images for social sharing
- [ ] Mermaid diagram rendering (for architecture diagrams)
- [ ] Screenshot gallery for Discord UI examples

### Not Needed (reference site has, ollim-bot doesn't need)
- ~~Enterprise/provider guides~~ (single-user project)
- ~~CI/CD integration guides~~ (no GitHub Actions usage)
- ~~Security/compliance/legal pages~~ (personal project)
- ~~Dynamic API-fetched components~~ (no registry to query)
- ~~Multi-surface install links~~ (Discord only)
