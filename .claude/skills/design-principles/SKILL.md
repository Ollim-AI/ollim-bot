---
name: design-principles
description: Software design and architecture principles. Apply when planning architecture, reviewing design decisions, auditing code structure, or evolving a codebase. Covers boundaries, coupling, extensibility, decision documentation, and agentic design failure modes.
argument-hint: [plan|audit|evolve] [path or topic]
---

# Software Design Principles

## Purpose

Every principle here exists to do one or more of these:

1. **Manage complexity** — keep the system understandable as it grows
2. **Enable change** — make the codebase adaptable without rewrites
3. **Preserve intent** — make design decisions visible and their rationale recoverable
4. **Prevent agentic drift** — guard against failure modes of AI-assisted design

**Scoring rubric**: Evaluate against [scoring-rubric.md](.claude/skills/design-principles/scoring-rubric.md) — exhaustively in audit mode (mark every item pass/fail/N/A with evidence), as end-of-plan verification in plan mode (mark every applicable item and flag any failures the plan should address before implementation), and targeted in evolve and open-ended modes (select items relevant to the growth direction under discussion, state which items you're checking and why). Each item maps to a principle below. Hard-rule violations are always worth reporting; strong-default and judgment-call violations should be prioritized by impact on changeability and complexity.

## How to Use

### Invocation modes

| Invocation | What Claude does |
|------------|-----------------|
| `/design-principles` (no args) | **First**, ask about design goals and constraints — analysis without goals is speculation. **Then** examine the project's structure and architecture docs with those goals as the lens. Identify implicit design decisions. Consider plausible growth directions. Flag decisions that may hinder change. |
| `/design-principles plan [topic]` | Enter a planning session. Ask about goals, constraints, and existing decisions before proposing architecture. Apply principles to the design. Flag decisions that need documenting. |
| `/design-principles audit [path]` | Scan code structure for principle violations. Score against the rubric. Prioritize findings by impact — boundary violations and coupling issues before naming concerns. |
| `/design-principles evolve` | Analyze current architecture against likely growth directions. Check if key decisions are documented. Flag structural decisions that would make expansion difficult. |

For invocations that don't match a recognized mode (e.g., `/design-principles refactor`), treat the arguments as a topic and use **plan mode** behavior. For modes missing required context (e.g., `/design-principles audit` with no path), ask what scope to target rather than guessing.

### Before giving design advice

1. **Check for existing architecture docs** — look for ADRs, architecture docs, CLAUDE.md design sections, or README architecture sections. The current design may be intentional and documented.
2. **Scan existing conventions** — read the codebase to understand current patterns before proposing new ones. Match what exists unless there's a specific reason to diverge.
3. **Ask about design goals** — "What are the design goals?" and "What constraints exist (team size, deployment model, performance requirements)?" Without these, design advice is generic and potentially wrong.

### Priority when principles conflict

1. **Don't break what works** — existing architecture that functions is more valuable than theoretical purity
2. **Match existing conventions** — consistency within a codebase beats individual principle compliance
3. **Irreversible over reversible** — spend design effort proportional to reversal cost
4. **Simplicity over completeness** — a simple design that covers 90% of cases beats a complex one covering 100%

### Applying principles in audit mode

In audit mode, principles describe the target state — not a refactoring mandate. For each violation found:
- **State the principle violated** and where in the code
- **Assess impact**: does this violation actively impede change, or is it a cosmetic deviation?
- **Estimate effort**: is this a localized fix or a structural rework?

Prioritize findings that impede change over findings that violate style. Don't propose a refactoring plan unless the user asks — audit mode is diagnostic.

**Reading the principles below**: Imperative language ("remove", "split", "extract", "fix") describes what the target state requires — not an instruction to immediately refactor. In audit and evolve modes, identify deviations and assess their impact; don't act on them unless the user asks.

### Applying principles in existing codebases

Principles describe the target state for well-designed systems. In existing codebases, not every deviation is worth fixing. Flag deviations proportional to their impact on maintainability. Match existing conventions unless diverging solves a concrete problem.

## Manage Complexity

**Define explicit boundaries** *(strong default)*: Every system has boundaries — between modules, services, layers. Make them visible through defined interfaces (function signatures, protocols, API contracts). A boundary answers: what does this component expose, and what does it hide? Code without explicit boundaries grows into a tangle where changing one thing breaks three others. In existing codebases, identify the implicit boundaries that already exist before drawing new ones. In small projects or scripts, implicit boundaries (file separation, clear function grouping) are sufficient — formal interfaces earn their keep as the system grows. At system edges (HTTP handlers, CLI parsers, database mappers), transform raw external data into typed domain objects immediately — deep code should never re-validate what the boundary already guaranteed.

**Cohesion within, coupling across** *(strong default)*: Code within a boundary should serve the same domain concept. If a module needs "and" to describe its purpose, split it. Across boundaries, minimize what's exchanged: pass data (values, typed models), not behavior (service objects, managers). The fewer types that cross a boundary, the easier each side is to change independently. Testability is a coupling signal — if you can't test a module without spinning up its neighbors, the coupling is too tight.

**Abstractions at boundaries, not everywhere** *(strong default)*: At module or service boundaries, depend on protocols/interfaces so the boundary is swappable — testing with a fake implementation counts as a concrete second use case. Inside a module, use concrete types directly. A protocol wrapping a single internal class that nothing else needs to swap is ceremony. The test: does anything (tests, a second implementation, a planned integration) need to substitute this? If only production code ever touches it, skip the protocol.

**No circular dependencies** *(hard rule)*: If module A depends on B, B must not depend on A — directly or transitively. Cycles mean the modules are logically one unit split artificially, or there's a shared concept that should be extracted into a third module. Fix the structure rather than working around it with lazy imports or runtime lookups. During active refactoring (incremental module extraction), a temporary lazy import with a TODO is acceptable — permanent lazy imports to mask structural cycles are not.

**Every layer earns its keep** *(strong default)*: If you trace a request through the system and a layer just delegates to the next without transforming data, enforcing rules, or adding meaningful behavior — that layer is a candidate for removal. Three to four meaningful layers is typical. More than that and you're paying an abstraction tax with no return. Before adding a new layer, articulate what it does that the layers above and below cannot.

## Enable Change

**Isolate what varies from what stays the same** *(judgment call — weigh evidence of likely change)*: When a part of the system is likely to change (data sources, business rules, output formats, third-party integrations), put it behind a boundary so changes don't ripple outward. When a part is stable and well-understood, inline it — don't add indirection "just in case." The judgment call: will this specific thing actually change based on evidence, or am I speculating?

**Prefer reversible decisions** *(strong default)*: Not all decisions are equal. Database schema changes, public API contracts, and data format choices are expensive to reverse. Internal module structure, in-memory data representations, and library choices are cheap to reverse. Spend design time proportional to reversal cost. For cheap-to-reverse decisions, pick one and move on — you'll learn more from building than from deliberating.

**Extend through composition, not modification** *(strong default)*: When adding new behavior, prefer composing new components (a new pipeline step, a new handler, a new strategy) over editing existing monolithic code. This keeps existing behavior untouched and testable. But don't build a plugin system for one plugin — composition patterns are justified when you have or clearly foresee multiple variants based on evidence.

**YAGNI with escape hatches** *(judgment call — weigh evidence, not speculation)*: Don't build features or abstractions for hypothetical future requirements — predictions about future needs are usually wrong. But don't paint yourself into corners either. The distinction: building a feature nobody asked for is waste. Using a hard-coded assumption (e.g., "there will only ever be one tenant") when the domain suggests otherwise is a corner. Ask: does this decision lock me in, or just mean more work later? Locked in is worth addressing now. More work later is acceptable.

**Single source of truth for state** *(hard rule)*: Each piece of mutable state should have exactly one authoritative location. Duplicated state drifts — when the same fact lives in two places, they will eventually disagree. Derived data should be computed, not stored. Push mutable state to the edges (databases, caches, sessions) and keep core logic as pure functions — data in, data out.

## Preserve Intent

**Document decisions, not descriptions** *(strongly recommended for multi-module decisions, optional for single-module choices)*: Code describes what it does. Documentation should capture what code cannot: *why* this approach was chosen, what alternatives were considered and rejected, and what constraints drove the decision. For decisions that affect multiple modules or would be expensive to reverse, write a short ADR (Architectural Decision Record): context, decision, consequences. Store them alongside the code (e.g., `docs/decisions/`). Before proposing architectural changes, check for existing ADRs — the current design may be a deliberate tradeoff.

**Name for the domain, not the pattern** *(strong default)*: Modules, classes, and services should use the problem domain's vocabulary. `payments/` over `strategy_pattern/`. `OrderProcessor` over `OrderHandlerFactoryImpl`. If understanding a name requires knowing a design pattern, it's the wrong name — because domain names survive refactors while pattern names become lies when the underlying pattern changes. Exception: infrastructure and utility code where the pattern IS the domain concept — `ConnectionPool`, `RetryPolicy`, `EventBus` are appropriate names because they describe what the thing actually is, not an implementation detail.

**Make the architecture navigable** *(strong default)*: A new developer — or a new Claude session — should understand the system's high-level structure from the top level. This means: directory names that reflect domain concepts, a top-level doc explaining major components and how they connect, and entry points that are discoverable. If understanding the architecture requires tribal knowledge, the architecture is underdocumented.

## Prevent Agentic Drift

These are failure modes specific to designing systems with AI assistants. Each includes the tendency, why it happens, and how to counter it. When designing with Claude, actively watch for these.

**Over-engineering**: Claude introduces abstractions, patterns, and layers beyond what current requirements need because it has seen many "well-architected" codebases in training. Every abstraction is a prediction about future requirements — and predictions are usually wrong. *Counter*: for every proposed abstraction, demand a concrete, present use case. "We might need this later" fails the test. If only one thing implements an interface, the interface is premature.

**Pattern fetishism**: Applying design patterns (Factory, Strategy, Observer, Registry) because they "fit" structurally, not because they solve a concrete problem in this codebase. A pattern without a problem is complexity without value. *Counter*: name the specific problem the pattern solves in *this* codebase, not in a textbook.

**Scope creep during design**: "While we're designing this, we should also handle..." — expanding design scope beyond what was asked. Each expansion multiplies implementation time and introduces decisions that haven't been thought through. *Counter*: separate "what we're building now" from "what we might build later." Capture ideas for later; design only for what's needed now.

**Cargo culting**: Copying architectural patterns from popular projects or frameworks without considering whether they fit this project's constraints. Microservices for a solo developer. Event sourcing for simple CRUD. Domain-driven design for a 500-line script. *Counter*: every architectural pattern must justify itself against the project's actual scale, team size, and complexity.

**Invisible decisions**: Making design choices without surfacing them to the user. Claude may restructure code in ways that embed architectural decisions the user didn't explicitly approve — choosing a data flow pattern, establishing module boundaries, or picking a state management approach. *Counter*: when a design choice has meaningful alternatives, present options before implementing. State: "I'm choosing X over Y because Z — does that align with your goals?"

**Inconsistency with existing architecture**: Proposing new patterns in a codebase that already has established conventions for the same concern. The codebase uses repositories; Claude introduces direct queries. The codebase uses event-driven communication; Claude adds synchronous calls. *Counter*: always scan existing code for conventions before proposing new patterns. Match what exists unless there's a documented reason to diverge.

**Gold plating**: Adding unrequested polish — extra validation, comprehensive logging, metrics instrumentation, flexible configuration — that wasn't asked for and doesn't serve an immediate need. Each addition is code to maintain and reason about. *Counter*: implement exactly what was requested. Suggest improvements separately; don't bundle them in.

**Analysis paralysis**: Spending more time deliberating about design than it would take to build, test, and refactor. For decisions that are cheap to reverse, building something and learning from it is faster than theorizing. *Counter*: for reversible decisions, timebox the design discussion. If you can't decide in 5 minutes, build the simpler option and iterate.

## When to Ask for Clarification

**Always ask when:**
- The project's design goals are unknown — design advice without goals is generic
- A proposed change affects module or service boundaries
- Two principles conflict for the specific case (e.g., YAGNI vs. avoiding an irreversible lock-in)
- The current architecture appears suboptimal but might be a documented, intentional decision
- A design choice has meaningful alternatives worth considering

**Don't ask when:**
- The design direction is clear from existing architecture and conventions
- The principle application is straightforward and unambiguous
- The question is about naming or cosmetic concerns, not structural ones
