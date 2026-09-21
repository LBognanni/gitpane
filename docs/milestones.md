# Better Tests milestone

`docs/better-tests.md` is the authoritative initiative for this milestone. This
file turns that initiative into ordered, independently reviewable stories. The
milestone changes tests and test documentation only; it does not change product
behavior.

## Goal

Make the suite describe observable behavior at the narrowest stable boundary
while remaining fast and deterministic. Application tests continue to mock Git,
Git adapter tests continue to treat generated commands as outcomes, and UI
presentation is tested through mounted components rather than TCSS source.

## Scope and locked decisions

- Do not modify `gitpane/`, `pyproject.toml`, dependencies, or product behavior.
  If a proposed behavioral test exposes a product defect, stop and report it;
  fixing the defect requires a separately planned milestone.
- Record the starting point with `uv run pytest` before moving tests.
- Complete all organizational moves in BT-S1 through BT-S3 before changing any
  assertion. Moves may change imports and fixture location only; test bodies,
  names, scenario data, and assertions remain byte-for-byte equivalent.
- Keep complete workflows together. `tests/test_app.py` retains startup,
  shortcuts, top-level navigation, refresh, file-tree construction, and commit
  selection. Keep `tests/test_code_view.py`, `tests/test_diff.py`, and
  `tests/test_git.py` as their existing component/parser/adapter boundaries.
- The autouse `build_diff_view.cache_clear()` fixture moves with diff rendering
  tests to `tests/test_diff_rendering.py`. Do not put it in `conftest.py` or
  apply it to unrelated application tests.
- Add `tests/conftest.py` only if at least two final test modules genuinely need
  the same setup. Keep one-off app classes, fakes, and scenario data local.
- Application tests mock `gitpane.git` with realistic status, history, file,
  preview, and diff responses, then assert visible UI state. Do not invoke Git
  or create real repositories outside `tests/test_git.py`.
- `tests/test_git.py` may continue asserting command arguments. Parser and pure
  formatting tests may continue asserting returned structured values.
- Prefer visible text, rendered strips, computed styles, focus, enabled state,
  scrolling, copied text, notifications, and adapter calls. Do not assert
  request-token values, document generations, object identity, cache storage,
  private visual-row arrays, private compositor state, or helper call order.
- Never read or parse `gitpane/app.tcss` in a test. Never assert literal color
  codes. Mount the relevant component and inspect computed or rendered styles.
  Rich spans/strips are allowed only for the smallest meaningful styling
  contract.
- Preserve focused unit tests. Do not replace pure-function tests with broad app
  tests, and do not broaden a workflow merely to avoid a useful mock.
- Cache behavior has one explicit performance contract: preparing the same
  `(entry, patch)` twice avoids repeating expensive parse/highlight/render work.
  Cache capacity and eviction order are not product requirements and are not
  tested.
- Virtual rendering has one explicit performance contract: repaint work for a
  fixed viewport is bounded by viewport size rather than total document length.
  Prove this by comparing observable rendering work for small and large
  documents, not by prescribing an exact `render_line()` sequence.
- Keep concurrency tests that prove responsiveness, non-overlap, ordering, and
  newest-result-wins behavior. Use events or controlled futures for deterministic
  completion order, but assert the final visible outcome.
- Every coder prompt must include: **“Do NOT boot the editor or run any
  browser/smoke test.”** It must also include: **“NEVER use `git stash`,
  `git checkout --`, or `git restore` on any file you did not intentionally edit
  for this task. If something unexpected changes, STOP and report it.”**
  Architectural uncertainty is escalated to a `senior-coder`; do not guess.
- No subagent starts a later story, commits, or edits phase-summary prose before
  the active story is reviewed and accepted. The orchestrator alone may update
  the status table after each accepted story in its separate documentation
  commit. BT-S9 is the only implementation story allowed to edit phase-summary
  prose.

## Target test layout

| Path | Product behavior owned |
| --- | --- |
| `tests/test_app.py` | Startup, shortcuts, top-level navigation, refresh, file-tree construction, and commit selection |
| `tests/test_preview.py` | Preview loading, encoding/size failures, logical lines, line numbering, preview selection, wrapping, and preview scrolling |
| `tests/test_file_jump.py` | Matching, truncation, dialog behavior, and revealing nested files |
| `tests/test_diff_viewer.py` | Diff loading/application, navigation, scrolling, wrapping, stale results, and viewer errors |
| `tests/test_diff_rendering.py` | Diff construction, source reconstruction, syntax highlighting, cache contract, and rendered rows |
| `tests/test_status_actions.py` | File labels, stage/unstage/discard, bulk selection, unsupported entries, and action failures |
| `tests/test_app_concurrency.py` | Background status work, stale refreshes, refresh coalescing, and mutation serialization |
| `tests/test_code_view.py` | The `CodeView` component boundary |
| `tests/test_theme.py` | Mounted theme, contrast, interaction-state, and layout outcomes |

## Story plan

### BT-S1 — Extract diff rendering tests unchanged

**Outcome:** diff construction tests and their cache reset are isolated before
any assertion rewrite, and the rest of the suite no longer clears the diff cache
automatically.

**Verbatim story spec**

> Create `tests/test_diff_rendering.py` by moving, without rewriting, the
> `join_diff_lines` helper, the autouse `build_diff_view.cache_clear()` fixture,
> `test_load_diff_view_forwards_root_and_entry_to_git_diff_then_builds`, and all
> tests from `test_build_diff_view_prepares_independent_lines_without_a_joined_document`
> through `test_render_diff_rows_projects_highlights_by_new_side_position` out of
> `tests/test_app.py`. Preserve every moved test body, name, parameter, mock,
> scenario, and assertion. Change only imports and fixture placement needed for
> collection. Do not add `tests/conftest.py`, rewrite assertions, or touch product
> code. Run the full suite after the move so fixture-scope mistakes are visible.

**Target paths**

- Modify `tests/test_app.py`.
- Add `tests/test_diff_rendering.py`.

**Dependencies:** none. Before editing, record the baseline with
`uv run pytest` and report its result.

**Verification**

```bash
uv run pytest tests/test_app.py tests/test_diff_rendering.py
uv run pytest
uv run ruff check tests/test_app.py tests/test_diff_rendering.py
uv run ruff format --check tests/test_app.py tests/test_diff_rendering.py
uv run mypy gitpane tests
```

### BT-S2 — Extract preview and file-jump tests unchanged

**Outcome:** preview and quick-file-jump workflows have focused homes, with no
behavior or assertion changes.

**Verbatim story spec**

> Move preview behavior from `tests/test_app.py` to a new
> `tests/test_preview.py`: all `load_preview_view` tests,
> `test_file_selection_shows_repository_relative_path`,
> `test_loaded_preview_uses_current_wrap_setting`,
> `test_file_preview_scrollbar_track_click_jumps_to_clicked_position`, and the
> preview half of any helper imports they require. Move matching/truncation and
> `test_quick_file_jump_is_memory_backed_and_reveals_nested_file` to a new
> `tests/test_file_jump.py`. Preserve test bodies, names, mocks, and assertions;
> only repair imports. Keep one-off data and fakes local and do not create
> `tests/conftest.py`. Do not rewrite token, call-count, widget, or style
> assertions yet, and do not touch product code.

**Target paths**

- Modify `tests/test_app.py`.
- Add `tests/test_preview.py`.
- Add `tests/test_file_jump.py`.

**Dependencies:** BT-S1 accepted.

**Verification**

```bash
uv run pytest tests/test_app.py tests/test_preview.py tests/test_file_jump.py
uv run pytest
uv run ruff check tests/test_app.py tests/test_preview.py tests/test_file_jump.py
uv run ruff format --check tests/test_app.py tests/test_preview.py tests/test_file_jump.py
uv run mypy gitpane tests
```

### BT-S3 — Complete the behavioral split unchanged

**Outcome:** `test_app.py` owns only its declared top-level behaviors; diff,
status-action, and concurrency workflows are organized for narrow rewrites.

**Verbatim story spec**

> Finish splitting `tests/test_app.py` without changing test behavior. Move diff
> viewer composition/application, change navigation, scrolling, wrapping,
> selection/copying, request clearing, stale diff application, diff errors,
> scrollbar helper, and viewer paging tests to `tests/test_diff_viewer.py`. Move
> file-label tests, `toggle_file`, `discard_files`, single/bulk status actions,
> unsupported entries, Git/action failures, status-failure handling, and
> `is_prefix_offset` tests to `tests/test_status_actions.py`. Move
> `is_current_request`, background status-thread, stale refresh-apply,
> refresh-coalescing, and serialized-mutation tests to
> `tests/test_app_concurrency.py`. Leave startup, first-launch shortcuts,
> keyboard/top-level navigation, initial refresh/file-tree construction, commit
> label/selection, and their local helpers in `tests/test_app.py`. Preserve all
> moved test bodies, names, mocks, and assertions exactly; change imports only.
> Do not create broad shared fixtures or touch product code.

**Target paths**

- Modify `tests/test_app.py`.
- Add `tests/test_diff_viewer.py`.
- Add `tests/test_status_actions.py`.
- Add `tests/test_app_concurrency.py`.

**Dependencies:** BT-S2 accepted. No assertion-rewrite story may start until
BT-S3 is accepted.

**Verification**

```bash
uv run pytest tests/test_app.py tests/test_diff_viewer.py tests/test_status_actions.py tests/test_app_concurrency.py
uv run pytest
uv run ruff check tests
uv run ruff format --check tests
uv run mypy gitpane tests
```

### BT-S4 — Test theme and layout through mounted output

**Outcome:** theme, contrast, list states, title layout, and responsive pane
behavior are connected to the actual mounted stylesheet and rendered widgets.

**Verbatim story spec**

> Rewrite `tests/test_theme.py` so no test opens, parses, regex-matches, or
> otherwise inspects `gitpane/app.tcss`, and no assertion contains a literal
> hex/RGB color. Mount the smallest representative app/components with
> `run_test()`. Obtain foregrounds, backgrounds, borders, scrollbar/indicator
> colors, and selection styles from computed widget styles or rendered strips.
> Keep WCAG floors of 4.5 for text and 3.0 for indicators, but calculate them
> from mounted states. Use `Pilot` to exercise ordinary, hovered, highlighted,
> focused, and selected list rows and assert the semantic hierarchy without
> selector-order assumptions. Render a long status path in a constrained list
> and prove it occupies one row. Render a long diff title and prove navigation
> remains visible and right-aligned. Resize a mounted app and assert usable pane
> dimensions, vertical/horizontal scrolling, and wrapped overflow behavior.
> Cover diff add/remove styling through rendered rows in a mounted `CodeView`
> without comparing it to TCSS variables. Remove obsolete stylesheet helpers
> and path imports. Do not modify TCSS or product code.

**Target paths**

- Modify `tests/test_theme.py`.

**Dependencies:** BT-S3 accepted.

**Verification**

```bash
uv run pytest tests/test_theme.py
uv run ruff check tests/test_theme.py
uv run ruff format --check tests/test_theme.py
uv run mypy gitpane tests
```

### BT-S5 — Express diff preparation as output contracts

**Outcome:** diff tests prove returned and rendered content, syntax projection,
and the documented cache benefit without locking in representations or helper
call sequences.

**Verbatim story spec**

> Rewrite brittle tests in `tests/test_diff_rendering.py`. For
> `load_diff_view`, mock only `git.diff`, return a realistic unified patch, and
> assert the resulting `DiffView` text/styles/change positions instead of
> mocking `build_diff_view`. Replace tuple/no-`text` representation assertions
> with visible row text and meaningful styles. For an identical `(entry, patch)`
> cache key, inject or mock one expensive parse/highlight/render boundary and
> prove it runs once, but do not assert object identity. Delete the five-key LRU
> eviction test because capacity/eviction order is not a requirement. For
> changed patch and changed entry, assert changed visible output and remove exact
> collaborator-call sequences. Parameterize representative filenames/source for
> lexer selection or resulting syntax styling. Preserve blank-line alignment and
> projected syntax styles, but remove the one-whole-pass and all-removals
> optimization assertions. For all-removal input, assert final rendered rows.
> In rendered-row tests keep exact plain gutter/source text plus meaningful
> foreground/background coverage, but remove helper-call assertions and
> duplicated exact span-layout checks. Do not alter pure source-reconstruction
> outcomes or product code.

**Target paths**

- Modify `tests/test_diff_rendering.py`.

**Dependencies:** BT-S4 accepted.

**Verification**

```bash
uv run pytest tests/test_diff_rendering.py tests/test_diff.py
uv run ruff check tests/test_diff_rendering.py
uv run ruff format --check tests/test_diff_rendering.py
uv run mypy gitpane tests
```

### BT-S6 — Test CodeView through rendering and interaction

**Outcome:** the component suite proves displayed content, viewport behavior,
selection, wrapping, and viewport-scaled work without private storage or
generation assertions.

**Verbatim story spec**

> Rewrite brittle cases only in `tests/test_code_view.py`. For document setting
> and equal replacement, assert displayed content, reachable scroll extent,
> repaint, and reset viewport; remove `document_generation` assertions. Replace
> the large-document exact `render_line` request proxy with a small-versus-large
> comparison showing work remains bounded by the same viewport height rather
> than total line count. Exercise page keys on a mounted widget and assert final
> viewport positions immediately, without monkeypatching scroll methods or
> checking `animate` arguments. Keep copied/selected source text and inspect
> rendered continuation strips, but remove every read of `_visual_lines`,
> `_visual_source_rows`, and `_visual_source_offsets`. For wrapped resize,
> capture visible source text and selected text before resize and prove both
> remain stable afterward. Replace private compositor inspection in replacement
> coverage with public rendered-strip or visible-text evidence. Retain narrow
> tests for dimensions, cell-width cropping, styles, bounded keyboard/scrollbar
> navigation, blank-line selection, and wrapping progress where they already
> assert outcomes. Do not change `CodeView` product code.

**Target paths**

- Modify `tests/test_code_view.py`.

**Dependencies:** BT-S5 accepted.

**Verification**

```bash
uv run pytest tests/test_code_view.py
uv run ruff check tests/test_code_view.py
uv run ruff format --check tests/test_code_view.py
uv run mypy gitpane tests
```

### BT-S7 — Prove stale-work behavior by controlled completion

**Outcome:** asynchronous tests demonstrate newest-result-wins UI behavior,
responsiveness, coalescing, and serialization without testing token mechanisms.

**Verbatim story spec**

> In `tests/test_app_concurrency.py`, remove the direct unit test of
> `is_current_request` and replace direct stale `apply_*` calls with delayed
> mocked `git.status`, `git.commits`, and `git.files` responses completed in a
> controlled out-of-order sequence. Assert that only the newest branch label,
> status lists, commit tree, and file tree are visible. In
> `tests/test_diff_viewer.py`, drive two realistic mocked diff loads to complete
> out of order and assert the newer title, rendered content, wrap setting, and
> scroll position remain visible after the older load completes. Do not inspect
> request IDs/tokens or document generations. Retain and only minimally adjust
> existing tests that prove Git work leaves the event thread, refreshes do not
> overlap, mutations serialize, controls remain responsive, and final UI state
> is correct. Use deterministic events/futures with bounded waits; do not invoke
> Git, sleep for timing, or modify product code.

**Target paths**

- Modify `tests/test_app_concurrency.py`.
- Modify `tests/test_diff_viewer.py`.

**Dependencies:** BT-S6 accepted.

**Verification**

```bash
uv run pytest tests/test_app_concurrency.py tests/test_diff_viewer.py
uv run ruff check tests/test_app_concurrency.py tests/test_diff_viewer.py
uv run ruff format --check tests/test_app_concurrency.py tests/test_diff_viewer.py
uv run mypy gitpane tests
```

### BT-S8 — Trim mixed application workflow proxies

**Outcome:** remaining app workflows assert user-visible results and adapter
boundaries rather than widget strategy, request machinery, or method calls.

**Verbatim story spec**

> Trim the mixed tests identified by `docs/better-tests.md` without broadening
> their workflows. In `tests/test_file_jump.py`, keep dialog, filtering,
> expansion, selected-node, and visible-preview assertions; remove request-token
> and exact `load_preview` call assertions. Retain a mocked `git.files` call
> count only as the explicit memory-backed-search requirement. In
> `tests/test_app.py`, let commit-file selection consume a realistic mocked
> `git.diff` and assert expanded tree, title, and displayed diff content instead
> of an internal `load_diff` call/token. In `tests/test_diff_viewer.py`, replace
> `test_app_uses_two_virtual_code_views` with independent large diff/preview
> display, replacement, scrolling, and wrapping outcomes; remove concrete
> `CodeView`/`JumpScrollBar` strategy assertions, mocked page-method calls, and
> the generation assertion from scrolled diff replacement while preserving
> visible content and scroll reset. In `tests/test_preview.py`, keep final
> scrollbar/page movement and visible preview outcomes without concrete
> scrollbar type checks. Delete redundant coverage when the same behavior is
> already proved at the narrower `tests/test_code_view.py` boundary. Do not
> change formatting tests, Git adapter tests, parser tests, or product code.

**Target paths**

- Modify `tests/test_app.py`.
- Modify `tests/test_file_jump.py`.
- Modify `tests/test_diff_viewer.py`.
- Modify `tests/test_preview.py`.

**Dependencies:** BT-S7 accepted.

**Verification**

```bash
uv run pytest tests/test_app.py tests/test_file_jump.py tests/test_diff_viewer.py tests/test_preview.py tests/test_code_view.py
uv run ruff check tests
uv run ruff format --check tests
uv run mypy gitpane tests
```

### BT-S9 — Final audit and milestone cleanup

**Outcome:** the reorganized suite satisfies every Better Tests completion
criterion, all quality gates pass, and milestone documentation records the
reviewed result.

**Verbatim story spec**

> Audit the complete test suite against `docs/better-tests.md` and this
> milestone. Use targeted searches to ensure no test parses `app.tcss`, asserts
> literal presentation colors, reads `_visual_lines`, `_visual_source_rows`, or
> `_visual_source_offsets`, asserts request-token values/document generations,
> or checks cache object identity/capacity. Confirm `tests/test_app.py` contains
> only its declared top-level behaviors, Git remains mocked in application
> tests, and `tests/test_git.py` command-boundary coverage is unchanged. Make
> only the smallest test cleanup needed for those criteria; do not alter product
> code or weaken observable behavior. Run the full quality gates. After the
> reviewed test diff is accepted, update only the status/completion prose in
> `docs/milestones.md`; do not rewrite the authoritative initiative in
> `docs/better-tests.md` or any other phase-summary document.

**Target paths**

- Modify `tests/test_app.py`, `tests/test_preview.py`,
  `tests/test_file_jump.py`, `tests/test_diff_viewer.py`,
  `tests/test_diff_rendering.py`, `tests/test_status_actions.py`,
  `tests/test_app_concurrency.py`, `tests/test_code_view.py`, and
  `tests/test_theme.py` only where the audit finds a remaining milestone
  violation.
- Modify `docs/milestones.md` only after test cleanup is reviewed and accepted.

**Dependencies:** BT-S1 through BT-S8 accepted.

**Verification**

```bash
! rg 'app\.tcss|_visual_lines|_visual_source_rows|_visual_source_offsets|document_generation' tests
! rg 'assert .*?(request_(id|token)|preview_request_id|status_request_id|history_request_id|files_request_id)' tests
! rg '#[0-9a-fA-F]{6}|rgb\(' tests/test_theme.py
uv run ruff check .
uv run ruff format --check .
uv run mypy gitpane tests
uv run pytest
```

Expected: all searches and quality commands pass; no browser, smoke test, editor
boot, real repository, or real Git invocation is part of verification.

## Completion criteria

- The target test layout is in place and `tests/test_app.py` contains no
  unrelated preview, rendering, status-action, or concurrency suites.
- No test reads `_visual_lines`, `_visual_source_rows`, or
  `_visual_source_offsets`, or asserts request-token values/document generations.
- Theme/contrast/layout tests use mounted computed or rendered appearance; no
  test parses TCSS or asserts literal color codes.
- Cache coverage states the repeated-work performance contract and does not
  prescribe identity, capacity, or eviction mechanics.
- Stale-result coverage controls completion order and proves only the newest
  visible result wins.
- Application tests mock Git with realistic data and remain fast; adapter tests
  continue to protect path and command semantics.
- `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and
  `uv run mypy gitpane tests` pass.

## Status

| Story | Status | Depends on | Primary deliverable |
| --- | --- | --- | --- |
| BT-S1 — Diff rendering split | Accepted | — | Focused rendering module and scoped cache fixture |
| BT-S2 — Preview/file-jump split | Accepted | BT-S1 | Focused preview and jump modules |
| BT-S3 — Complete app split | Accepted | BT-S2 | Viewer, status, and concurrency modules |
| BT-S4 — Mounted theme outcomes | Accepted | BT-S3 | Presentation tests connected to rendered UI |
| BT-S5 — Diff output contracts | Planned | BT-S4 | Behavioral preparation/render/cache coverage |
| BT-S6 — CodeView outcomes | Planned | BT-S5 | Public rendering, selection, and viewport coverage |
| BT-S7 — Controlled stale work | Planned | BT-S6 | Newest-result-wins concurrency workflows |
| BT-S8 — Mixed workflow trim | Planned | BT-S7 | Visible application outcomes without internal proxies |
| BT-S9 — Final audit/cleanup | Planned | BT-S1–BT-S8 | Passing gates and completed milestone record |
