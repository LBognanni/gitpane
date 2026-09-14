# Instructions for agents

- Use `uv` instead of raw python
- ruthlessly apply the KISS principle: keep it simple, avoid unnecessary complexity, and focus on the core functionality.
- Test the application logic but don't test git itself. The git commands are assumed to be correct and don't need to be tested.
- Mark performance and benchmark tests with `@pytest.mark.performance`.
- Exclude performance tests during routine feature work with `uv run pytest -m "not performance"`. Run them explicitly with `uv run pytest -m performance` only when working on performance or when the user requests them.

## Project context

- Read `docs/milestones.md`, `docs/design-spec.md`, or `docs/workflow.md` only when the task concerns their milestone, design, or workflow.
