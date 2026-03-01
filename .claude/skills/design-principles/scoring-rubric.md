# Design Principles — Scoring Rubric

Use this checklist to evaluate design decisions after planning, reviewing, or evolving architecture. Each item is a yes/no check tied to a principle from SKILL.md.

**Interpreting results by severity:**
- **Hard rule** — a "no" is always worth reporting
- **Strong default** — a "no" is worth reporting when it actively impedes change or adds complexity
- **Judgment call** — a "no" should include context about why it may or may not matter here

Skip items that don't apply to the current scope. Items marked *(plan/evolve only)* evaluate process decisions that aren't observable from code — skip them in audit mode.

---

## Manage Complexity

| # | Check | Principle |
|---|-------|-----------|
| X1 | Are module/service boundaries explicit — defined by interfaces, not just file organization? | Explicit boundaries *(strong default)* |
| X2 | Can each module's purpose be described without using "and"? | Cohesion *(strong default)* |
| X3 | Do boundaries exchange data (values, typed models) rather than behavior (service objects)? | Coupling *(strong default)* |
| X4 | Do abstractions (protocols/interfaces) exist only at boundaries with multiple implementations or testing needs? | Abstractions at boundaries *(strong default)* |
| X5 | Are there zero circular dependencies between modules? | No circular dependencies *(hard rule)* |
| X6 | Does every layer in the call chain transform data, enforce rules, or add meaningful behavior — no pure delegation? | Every layer earns its keep *(strong default)* |

## Enable Change

| # | Check | Principle |
|---|-------|-----------|
| E1 | Is behavior likely to change isolated behind boundaries, while stable behavior is inlined? | Isolate what varies *(judgment call)* |
| E2 | Do irreversible decisions (schema, API contracts) have proportionally more documentation and rationale than reversible ones? | Reversible decisions *(strong default)* |
| E3 | Is new behavior added through new components, not by editing existing monolithic code? | Composition *(strong default)* |
| E4 | Are abstractions and features justified by current requirements? Escape hatches preventing irreversible lock-in are justified; speculative features are not. | YAGNI *(judgment call)* |
| E5 | Does each piece of mutable state have exactly one authoritative source? | Single source of truth *(hard rule)* |

## Preserve Intent

| # | Check | Principle |
|---|-------|-----------|
| I1 | Are multi-module design decisions documented with rationale (ADR or equivalent)? | Document decisions *(strongly recommended)* |
| I2 | Were existing ADRs/architecture docs checked before proposing changes? | Document decisions *(strongly recommended)* |
| I3 | Do module and service names use domain vocabulary, not pattern names? (Infrastructure where the pattern IS the domain concept — `ConnectionPool`, `EventBus` — is exempt.) | Domain naming *(strong default)* |
| I4 | Can the system's high-level structure be understood from the top level without tribal knowledge? | Navigable architecture *(strong default)* |

## Prevent Agentic Drift

| # | Check | Principle |
|---|-------|-----------|
| A1 | Does every abstraction have a concrete, present use case — not "we might need this"? | Over-engineering |
| A2 | Can every design pattern name the specific problem it solves in this codebase? | Pattern fetishism |
| A3 | Is the design scope limited to what was actually requested? | Scope creep |
| A4 | Does every architectural pattern justify itself against this project's constraints (team size, scale)? | Cargo culting |
| A5 | Were all significant design choices explicitly presented with alternatives? *(plan/evolve only)* | Invisible decisions |
| A6 | Were existing codebase conventions checked before proposing new patterns? | Inconsistency |
| A7 | Is the implementation limited to what was asked, without unrequested additions? | Gold plating |
| A8 | For reversible decisions, was design discussion timeboxed rather than exhaustive? *(plan/evolve only)* | Analysis paralysis |
