# Instructions for agents

- Use `uv` instead of raw python
- ruthlessly apply the KISS principle: keep it simple, avoid unnecessary complexity, and focus on the core functionality.
- use gitmoji when committing

## Testing

- Test observable outcomes at the narrowest stable boundary that expresses the requirement. A pure function's return value and a Git adapter's generated command are outcomes at their respective boundaries.
- Mock the Git adapter in application tests for speed and determinism. Use realistic status, history, file, and diff responses, then assert resulting UI state rather than internal application calls.
- Do not test Git's own behavior or invoke real repositories when a mocked adapter proves the application behavior.
- Tests in `tests/test_git.py` may assert command arguments and adapter results. These protect path safety, repository scope, porcelain usage, and command semantics without testing Git itself.
- Prefer visible text, rendered output, computed styles, focus, enabled state, scrolling, copied text, notifications, and adapter calls over private fields, request tokens, object identity, storage layout, or helper call order.
- Never test presentation by parsing TCSS files or asserting literal color codes. Mount the component, put it in the relevant state, and assert its rendered or computed appearance.
- Rich spans and rendered strips may be inspected when styling is the behavior, but assert only the smallest meaningful visual contract rather than duplicating exact internal span layouts.
- Test caching, virtualization, and threading only when they support an explicit behavioral or concurrency requirement. Assert the requirement, not incidental implementation mechanics.
- Organize test files by product behavior, not production methods or classes. Keep complete user workflows together, keep files focused, and move fixtures to `conftest.py` only when multiple test modules genuinely share them.
- Keep `tests/test_code_view.py` as the `CodeView` component boundary. Do not fold widget internals into application workflow tests.

## Project context

- Read `docs/milestones.md`, `docs/design-spec.md`, or `docs/workflow.md` only when the task concerns their milestone, design, or workflow.
