# Python Principles — Scoring Rubric

Use this checklist to evaluate code after writing, reviewing, or refactoring. Each item is a yes/no question tied to a principle from SKILL.md. A "no" answer is a violation worth fixing. Skip items that don't apply to the change scope. Most changes will only hit a subset of checks.

---

## Reduce Future Bugs

| # | Check | Principle |
|---|-------|-----------|
| B1 | Do all new/modified functions have full type annotations (params, return, generics)? | Type hints |
| B2 | Are structured types used instead of `dict[str, Any]` at modified boundaries? | Structured types |
| B3 | Are constrained values modeled with `Enum`, `Literal`, or union types — not bare `str`/`int`? | Illegal states |
| B4 | Is `Optional` used only where `None` has domain meaning? | Optional |
| B5 | Is unstructured input parsed into typed models at entry points? | Parse at boundary |
| B6 | After parsing, are values accessed directly without defensive `.get()` or `getattr` fallbacks? | Fail fast |
| B7 | Are exceptions caught by specific type only — no broad `except Exception` or bare `except`? | Specific exceptions |
| B8 | Are caught exceptions handled meaningfully — no `except: pass` or `return None`? | Specific exceptions |
| B9 | Can every try/except block name the specific exception type and the condition that causes it? | Fail fast |
| B10 | Are there zero circular imports? | Circular imports |
| B11 | Are dataclasses marked `frozen=True` where mutation isn't needed? | Immutability |

## Aid Comprehension

| # | Check | Principle |
|---|-------|-----------|
| C1 | Does each function operate at one abstraction level — no mixing orchestration with string parsing? | Single level of abstraction |
| C2 | Is nesting at most 3 levels deep, using guard clauses and early returns? | Flat over nested |
| C3 | Do module names describe domain concepts — no `utils`, `helpers`, `misc`? | No kitchen-sink |
| C4 | Are functions pure where possible — input in, output out, no side effects? | Pure functions |
| C5 | Are docstrings present only where name + signature leave genuine ambiguity? | Document contracts |
| C6 | Do inline comments explain *why*, not *what*? | Document contracts |
| C7 | Are tests named after the behavior: `test_expired_token_returns_unauthorized`, not `test_auth`? | One assertion per behavior |

## Remove Misunderstanding

| # | Check | Principle |
|---|-------|-----------|
| M1 | Could you describe what each new/modified function does without using "and"? | Single responsibility |
| M2 | Are transport, business logic, and persistence in separate layers (in new modules)? | Separation of concerns |
| M3 | Are method chains limited to data access — no `service.get_repo().find(id).process()`? | Law of Demeter |
| M4 | In batch contexts, are parse failures caught at record level (log and skip), not field level? | Parse at boundary |

## Achieve Same Impact in Less Code

| # | Check | Principle |
|---|-------|-----------|
| L1 | Are there zero premature abstractions — no base class/protocol/factory for a single concrete case? | No premature abstraction |
| L2 | Are stateless classes replaced with module-level functions (in new code)? | Functions over stateless classes |
| L3 | Are there zero placeholders — no `TODO`, `FIXME`, `pass`, `...`, `NotImplementedError`? | No placeholders |
| L4 | Is there zero redundant validation after the boundary parse — no re-checking types or None on required fields? | Parse at boundary |
| L5 | Are new tests using the project's existing fixture/factory patterns — no new testing patterns introduced? | Match existing test setup |
