---
name: python-principles
description: Python software engineering principles. Apply when writing, reviewing, or refactoring Python code. Covers structure, type safety, code quality, and testing.
---

# Python Engineering Principles

## Purpose

Every rule here exists to do one or more of these:

1. **Reduce future bugs** — eliminate classes of errors through types, structure, and explicit failure
2. **Aid comprehension** — make code readable without needing the author's context
3. **Remove misunderstanding** — prevent ambiguity in naming, contracts, and data flow
4. **Achieve the same impact in less code** — cut boilerplate, dead paths, and unnecessary abstraction

**Scoring rubric**: After writing or reviewing code, evaluate against [scoring-rubric.md](.claude/skills/python-principles/scoring-rubric.md) — mark each applicable item pass/fail with evidence (quote the code or name the function). Skip items outside the change scope. For any failing item on code you wrote or modified, fix it before presenting.

## Project Layout

**src layout, single config**: For new projects, use `src/package_name/` with `pyproject.toml` as the single source of truth for metadata, dependencies, and tool config. Don't restructure existing projects to src layout — it breaks imports, CI, and deploy scripts. Keep `__init__.py` empty or limited to explicit public re-exports; never put logic in them.

**Right-sized modules**: Start with one module per concern at the top level. Promote to a sub-package when a module grows past ~400 lines or when 3+ modules share a domain boundary. If the top level grows past ~15 modules, group related ones. Never nest deeper than 2 levels. One class per file is a smell — merge it into its neighbor.

**No kitchen-sink modules**: Never create a module named `utils`, `helpers`, `misc`, or `common`. These become dumping grounds with no cohesion. Every module name should describe a domain concept. If a function has no clear home, the module structure is wrong — fix the structure. When encountering existing utils/helpers modules, don't refactor them as a side-effect of other work.

## Structure & Responsibility

**Single Responsibility**: Each module, class, and function should have one reason to change. If a function does fetching AND parsing AND saving, split it into three.

**Separation of Concerns**: In new modules, keep transport (HTTP/CLI), business logic, and persistence (DB/file) in separate layers — a service function should not import `Request` or `Session`, receive data in, return data out. In existing modules that mix layers, follow their current pattern rather than refactoring mid-feature.

**Single Level of Abstraction**: Each function should operate at one abstraction level. Don't mix orchestration (`process_order()`) with details (`line.strip().split(",")`) in the same function body. Extract the low-level work.

**No premature abstraction — but depend on abstractions when justified**: Never create a base class, protocol, factory, or registry to handle one concrete case. Abstractions are justified only when a second, *concrete and present* use case demands them, or when crossing a system boundary that testing requires to be swappable. "We might need this later" is not a use case. Three similar lines of code are cheaper than a wrong abstraction. When a second use case does arrive, refactor then — and depend on the abstraction (protocol/interface), not the concrete implementation.

**Functions over stateless classes**: In new code, if a class has no `__init__` state (or only config that could be parameters), use module-level functions instead. `class UserService` with methods that don't access `self` is just a namespace — use a module. Reserve classes for objects that manage state or implement protocols. Don't convert existing stateless classes unless the change is scoped to that module alone.

## Type Safety & Data Modeling

**Type hints on new and modified functions**: Every new or modified function signature gets full type annotations — parameters, return types, and generic types. Never use `Any` unless the value is genuinely unconstrained. Use `TypeVar` and `Generic` (or PEP 695 type parameter syntax on 3.12+) when needed. Don't retroactively type untouched functions — it can surface cascading type errors outside the task scope.

**Structured types over raw dicts**: Use dataclasses, Pydantic models, NamedTuples, or TypedDicts — never pass `dict[str, Any]` through multiple function calls. Structured types give autocompletion, validation, and self-documentation. Introduce structured types at boundaries you're modifying; don't chase down every raw dict in existing code.

**Make illegal states unrepresentable**: Use `Enum`, `Literal`, and union types to constrain values at the type level. Instead of `status: str` with runtime checks for `"active" | "inactive"`, use `status: Literal["active", "inactive"]` or a dedicated enum.

**Avoid Optional unless absence is meaningful**: A field is `Optional` only when `None` carries domain meaning (e.g., "user has no middle name"). If a value must always exist after construction, type it as required. Never add `Optional` "just in case" — it forces None-checks on every consumer and creates dead code paths.

**Parse at the boundary, trust internally**: Convert unstructured input (JSON, CLI args, env vars, API responses) into typed models at system entry points. Use framework-level error handling for parse failures — FastAPI/Pydantic handle validation errors automatically, CLI frameworks handle argument errors. Once data is parsed into a model, all downstream code trusts the types — no re-validation, no `if field is not None` on required fields, no `.get()` with defaults on known keys. In batch/pipeline contexts, catch parse failures at the record level to log and skip bad records, not at the field level — don't let one malformed record crash an entire job.

## Code Quality

**Law of Demeter for behavior, not data**: Don't chain method calls through intermediaries — `service.get_repo().find(id).process()` hides coupling. But nested attribute access on data models is fine: `order.customer.address.city` on dataclasses/Pydantic models is accessing a data structure, not reaching through behavioral objects. The test: if any object in the chain could be swapped for a different implementation, the chain is too long.

**Flat over nested**: Use guard clauses and early returns to keep indentation shallow. Maximum 3 levels of nesting. Instead of `if valid: ... (deep nesting)`, flip to `if not valid: return` and keep the happy path at the base indentation level.

**Pure functions and immutability**: Prefer functions that take input and return output without side effects. Use `frozen=True` on dataclasses. Build new collections instead of mutating existing ones. Reserve mutation for performance-critical paths.

**Fail fast, no speculative fallbacks**: After parsing into typed models, access values directly — `model.key` not `getattr(model, "key", "")`. The types guarantee presence. At unparsed boundaries or external integrations where data shape isn't guaranteed, defensive access is appropriate. Never wrap code in try/except "just in case" — before adding error handling for a third-party call, read the actual docs or source code using tools (context7, WebFetch, Read). If you can't verify a failure mode exists, don't handle it. The only justified fallback is for *documented, unpreventable* unreliability (network timeouts to external services). Every fallback must answer: what specific failure does this handle, and why can't it be prevented upstream?

**Specific exception handling**: Never catch broad `except Exception` or bare `except` — catch specific exception types only. Don't swallow errors with `except: pass` or `except SomeError: return None`. Only catch where you can actually handle the error meaningfully; otherwise let it propagate up to a handler that can.

**No circular imports**: If module A imports from B, module B must not import from A. Break cycles by extracting shared types into a third module, or by using `TYPE_CHECKING` imports for annotation-only needs.

**No placeholders**: Never write `TODO`, `FIXME`, `pass`, `...` (ellipsis), or `NotImplementedError` in production code. Implement the actual behavior or don't write the function. Every function body must be complete and working.

## Documentation

**Document contracts, not mechanics**: Every module gets a one-line docstring stating its purpose. Default to NO docstring on functions — add one only when name + type signature leave genuine ambiguity about constraints, invariants, or non-obvious behavior. `def get_user(user_id: int) -> User` needs no docstring. `def __init__` never needs `"""Initialize the Foo."""`. Use Google-style format. Never duplicate type annotations in docstring prose. Inline comments explain *why*, never *what*.

## Testing

**Arrange-Act-Assert**: Structure every test in three phases separated by blank lines — set up inputs, execute the action, check the result. Never combine setup and assertion in one expression.

**Test behavior, not implementation**: Assert on observable outcomes (return values, state changes, collected side effects), not on internal method calls or execution order. Tests should survive refactors that preserve behavior.

**Prefer real implementations over mocks**: For new test files, prefer in-memory implementations of protocols over `unittest.mock`/`patch`/`MagicMock`. A `MessageSender` protocol gets an `InMemoryMessageSender` that appends to a list — assert on the list. These are real objects with real behavior that catch real bugs. In existing test files that use mocks, match the existing pattern to keep the file consistent.

**One assertion per behavior**: Each test function validates one logical behavior. Multiple `assert` statements are fine when verifying different aspects of the same outcome. But if testing two distinct scenarios, write two test functions. Name tests after the behavior: `test_expired_token_returns_unauthorized`, not `test_auth`.

**Match the existing test setup**: Before writing new tests, read the existing test files. Match the project's fixture patterns, factory conventions, and assertion style. Never introduce a new testing pattern when the project already has one.
