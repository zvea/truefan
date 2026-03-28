# Claude Code Guide

Read `DESIGN.md` to get oriented before starting any task.

## Design Docs

**Describe final state.** Write what the system *is*, not what it *gains*, *adds*, or *changes*.

**Design doc API scope: public only.** `DESIGN.md` covers public types, exceptions, functions, and constants — no underscore-prefixed names. Document private details in module docstrings and inline comments. When a private constant shapes behaviour, describe the effect, not the name or value.

## Feature Workflow

For any non-trivial feature:

1. **Discuss** — agree on scope and approach with the user.
2. **Design (data structures & API)** — update `DESIGN.md`.
   **STOP. Reply to the user and wait for explicit approval before continuing.**
3. **Design (test plan)** — describe the test scenarios verbally with the user.
   **STOP. Reply to the user and wait for explicit approval before continuing.**
4. **Tests** — implement the test cases; use function docstrings as the test plan.
5. **Implementation** — implement the feature.
6. **Review** — carefully examine the entirety of `DESIGN.md` and all changed code before declaring done.
7. **Commit** — do not commit. Wait for the user to explicitly ask.

Do not combine steps. Do not proceed to the next step without the user's reply.

Run unit tests after every non-trivial change. Always invoke pytest with `-n auto` to use parallel workers.

## Naming over Numbering

Prefer descriptive names over sequential numbers — in code (test functions, identifiers) and in documentation (section headings). Numbers require renumbering everything when items are added or removed; names remain stable.

## Testing

### Structure

Group tests by function under test, with a `#### function_name` header for each group.

### Coverage

Check with `pytest -n auto --cov --cov-report=term-missing`. Fill gaps that have a clear real-world trigger and test a meaningful contract. Skip defensive guards for impossible inputs and dunder methods. Do not target a percentage.

## Git

Do not commit unless the user explicitly asks you to.

Do not add "Co-Authored-By" or similar lines to commit messages.

## Experiments

One-off scripts live in `experiments/`; all output goes to `experiments/out/` (git-ignored). Name scripts descriptively. Never import experiments from the main package. Never commit experimental scripts unless the user specifically asks you to.

## Dependencies

Always ask before introducing any new dependency.

`pyproject.toml` must list every library the code imports directly under `[project] dependencies`, with a version constraint (`>=X.Y.Z`). It should not list libraries that are not directly imported, even if they are transitive dependencies. Dev-only dependencies go under `[project.optional-dependencies] dev`.

## Python Style Guide

- All imports at module level only — no inline or function-scoped imports.
- Every module and function must have a docstring: a brief description, plus any non-obvious behaviour or constraints worth noting. Omit obvious parameter/return documentation.
- All functions and methods must have type annotations on parameters and return values.
- Annotate module-level constants with `Final` and use immutable container types (`frozenset`, `tuple`, `MappingProxyType`) rather than mutable ones.
- Use built-in generic types, always parameterised: `list[int]` not `list` or `List[int]`, `dict[str, int]` not `dict` or `Dict[str, int]`, etc.
- Use `x | None` not `Optional[x]`.
- Prefer `@dataclass` over named tuples and dicts for structured data. Default to `@dataclass(frozen=True, kw_only=True)`.
- Prefer character literals over Unicode escape sequences: write `"°"` not `"\u00b0"`, `"Δ"` not `"\u0394"`, etc.
