# UI performance roadmap

The completed implementation milestones have been removed. This roadmap covers
the large-file performance work described in `docs/perf.md`.

# Milestone 1: Performance baseline

## Goal

Create a repeatable way to measure large diff and preview behavior before the
viewer architecture changes. The milestone is complete when the current
implementation can be profiled consistently at representative document sizes
and the results identify where time and memory are spent.

## Tasks

1. Add a benchmark or profiling harness for 1,000, 10,000, and 50,000 lines.
2. Cover normal source, densely highlighted source, mixed diff rows, long lines,
   vertical paging, scrollbar jumps, horizontal scrolling, resize, and wrapping.
3. Measure diff parsing, syntax highlighting, view construction, first render,
   repeated scrolling, wrap toggling, and retained cache memory separately.
4. Record the environment and baseline results so later milestones can be
   compared against the same workload.
5. Register a `performance` pytest marker and apply it to every benchmark,
   timing check, and resource-intensive performance workload.
6. Add only stable functional assertions to the normal test suite. Keep
   machine-dependent timing results report-only unless a reliable CI threshold
   is demonstrated.

## Acceptance criteria

- One documented command runs the benchmark from the repository root.
- `uv run pytest -m "not performance"` excludes every performance workload,
  while `uv run pytest -m performance` runs it explicitly.
- Workloads are deterministic and do not invoke or benchmark Git itself.
- Diff and preview measurements are reported separately.
- Rendering time is distinguishable from parsing and highlighting time.
- The results are sufficient to compare the existing `Static` viewer with a
  virtualized implementation.
- Ruff, formatting, mypy, and the existing test suite pass.

## Scope and locked decisions

- This milestone measures the current implementation; it does not optimize or
  refactor `gitpane/app.py`, change viewer behavior, add thresholds, or choose a
  virtualization design.
- Generate patches and preview source in memory or under pytest's temporary
  directory. Never create a repository or invoke `gitpane.git`, because Git is
  outside the benchmark boundary.
- Use only the standard library, pytest, and the project's existing Rich and
  Textual dependencies. In particular, do not add a benchmark framework or a
  process-memory dependency for this baseline.
- Use `time.perf_counter_ns()` for elapsed time and `tracemalloc` for attributed
  Python allocation measurements. Report samples and descriptive statistics;
  do not assert machine-dependent timing or byte thresholds.
- Exercise painting and interaction with Textual's headless `run_test()` at a
  fixed 120 by 40 terminal size. This is an automated pytest workload, not a
  manual app or browser smoke test. Do not boot the GitPane editor manually.
- Keep generated inputs deterministic and seed-free. Use the same workload IDs,
  dimensions, operation sequence, and report schema in later milestones.
- The benchmark matrix is intentionally not a Cartesian product. The ordinary
  preview and mixed-diff cases cover all 1,000, 10,000, and 50,000 line sizes;
  focused dense-highlight and long-line cases cover the documented worst cases
  without multiplying an already expensive suite.
- `uv run pytest -m performance` is the one root-level benchmark command. It
  writes the raw, machine-specific report to
  `.artifacts/performance-baseline.json`; `.artifacts/` is ignored. The reviewed
  comparison baseline is `docs/performance-baseline.md` and records selected
  results plus the exact environment and source revision.
- All files below `tests/performance/` are performance workloads and must carry
  `pytestmark = pytest.mark.performance` in each collected test module. Small,
  stable tests of generators and report formatting stay in the normal suite.
- Preserve a dirty worktree: inspect `git status --short` before editing, touch
  only story paths, never clean or restore unrelated files, and do not make a
  baseline result claim unless the recorded revision and dirty state are stated.

## Workload contract

The generators in `tests/performance/workloads.py` are the single source of
truth for these IDs and dimensions:

| Workload ID | Sizes | Required shape and purpose |
| --- | --- | --- |
| `preview-normal` | 1k, 10k, 50k | Short numbered Python assignment lines; remains below the 1 MiB preview limit and measures representative source. |
| `preview-dense` | 1k, 10k | Compact Python containing strings, numbers, calls, and punctuation on every line to produce dense syntax spans. |
| `preview-long` | 1k | Mostly ordinary rows with deterministic 4,096-column rows; isolates horizontal width and long-line behavior without an excessive fixture. |
| `diff-mixed` | 1k, 10k, 50k | One valid unified patch with repeating context/remove/add groups and changes away from row zero. |
| `diff-dense` | 1k, 10k | The mixed shape with compact, syntax-dense Python on the new side. |
| `diff-long` | 1k | The mixed shape with deterministic 4,096-column changed and context rows. |

“1k”, “10k”, and “50k” mean exactly 1,000, 10,000, and 50,000 source rows for
previews and exactly that many parsed `Row` values for diffs. Patch headers and
change pairing must be generated so `diff.parse()` returns the requested row
count. Every generator exposes metadata (ID, viewer, line count, maximum source
width, content byte count, and expected diff-kind counts) used in the report.

Preparation measurements run every workload above. Headless viewer measurements
run `preview-normal` and `diff-mixed` at all three sizes, plus the 1k dense and
long variants. For each viewer/workload combination report first render; ten
settled line scrolls; ten settled page scrolls; five settled scrollbar jumps;
five horizontal scrolls where content is wider than the viewport; resize from
120x40 to 100x30 and back; and wrap on/off. Report the complete sequence total
and per-operation samples so later code can improve one operation without hiding
a regression in another.

## Story plan

### M1-S1 — Register performance tests and deterministic workloads

**Outcome:** pytest can select an explicitly marked performance suite, and all
later measurements consume stable, validated synthetic content.

**Target paths**

- Modify `pyproject.toml` to register the `performance` marker with a concise
  description.
- Add `tests/performance/__init__.py` and
  `tests/performance/workloads.py` containing immutable workload metadata and
  simple preview/patch generators implementing the workload contract above.
- Add `tests/performance/test_selection.py` as the marked, inexpensive
  selection sentinel.
- Add `tests/test_performance_workloads.py` for fast generator-contract tests.

**Implementation notes**

1. Keep generation linear and direct: repeated formatted lines joined once.
   Avoid random data, fixture files, Git calls, parameter-object frameworks, or
   snapshots of megabytes of text.
2. Ensure preview fixtures intended for `load_preview_view()` are valid UTF-8
   and at or below `MAX_PREVIEW_BYTES`. Report bytes from UTF-8 encoding rather
   than character count.
3. Build syntactically valid unified patches directly. Use a tiny requested row
   count in normal tests to prove exact parsed count, kind distribution,
   deterministic output, first change placement, width metadata, and special
   dense/long characteristics. Do not generate 10k/50k content in the normal
   suite.
4. Add a marker-selection sentinel in
   `tests/performance/test_selection.py`, with module-level
   `pytestmark = pytest.mark.performance`, so both selection commands have an
   inexpensive collected performance test before the real benchmark lands.

**Dependencies:** none.

**Verification**

```bash
uv run pytest tests/test_performance_workloads.py
uv run pytest -m "not performance"
uv run pytest -m performance tests/performance/test_selection.py
uv run ruff check pyproject.toml tests/performance tests/test_performance_workloads.py
uv run ruff format --check tests/performance tests/test_performance_workloads.py
uv run mypy tests/performance tests/test_performance_workloads.py
```

Expected: normal selection does not run the sentinel; explicit selection does;
the fast contract tests prove deterministic shape without timing assertions.

### M1-S2 — Add report collection and preparation/memory measurements

**Outcome:** one isolated pytest run produces structured environment, parsing,
highlighting, construction, end-to-end preparation, and retained-memory data,
with diff and preview records kept separate.

**Target paths**

- Add `tests/performance/reporting.py` for sample collection, integer-nanosecond
  summaries, environment metadata, and deterministic JSON serialization.
- Add `tests/performance/conftest.py` with a session-scoped report fixture that
  writes `.artifacts/performance-baseline.json` even when no timing threshold is
  enforced.
- Add `tests/performance/test_preparation.py` for preparation and memory
  workloads; mark the module `performance`.
- Add `tests/test_performance_reporting.py` for small, stable summary/schema and
  serialization tests.
- Modify `.gitignore` to ignore `/.artifacts/`.

**Implementation notes**

1. Give every record these comparison keys: schema version, viewer (`diff` or
   `preview`), workload ID, line count, phase, operation, samples in integer
   nanoseconds or bytes, and min/median/max. Record Python implementation and
   version, platform, CPU description/count, total memory when available from
   portable standard-library/system sources, Rich/Textual/unidiff versions,
   terminal size, UTC timestamp, Git commit, and whether the worktree was dirty.
   Environment metadata collection may run read-only Git commands; timed
   workloads must not invoke Git.
2. Take at least three samples for 1k preparation cases and one sample for 10k
   and 50k cases. Clear `build_diff_view` between samples and call `gc.collect()`
   outside timed regions. Preserve raw samples so aggregation choices can be
   revisited.
3. Diff phases are: `parse` (`diff.parse`), `highlight`
   (`highlight_new_lines`), `view-construction` (`render_diff_rows` with the
   already-produced highlighted lines supplied by a scoped monkeypatch so lexing
   is excluded), and `prepare-total` (`build_diff_view` on a cold cache). This
   explicitly avoids double-counting highlighting as construction.
4. Preview phases are: UTF-8 decode/read preparation via `load_preview_view`,
   explicit Rich syntax highlighting of its `Syntax` content, lightweight view
   construction, and their documented total. Use `tmp_path` only for the bounded
   input read; do not include temporary-file creation in a timed region.
5. Use `tracemalloc` deltas/peaks after a collection boundary for (a) one active
   prepared diff, (b) one active prepared preview, and (c) the four-entry
   `build_diff_view` cache filled with distinct 50k mixed patches. Include
   `cache_info()` counts and label these as Python allocations, not process RSS.
6. Assertions are structural only: expected records exist, parsed row counts and
   viewer types are correct, all samples are non-negative, and the cache contains
   four entries. Never fail on elapsed time or allocated-byte magnitude.

**Dependencies:** M1-S1 workload IDs and marker registration.

**Verification**

```bash
uv run pytest tests/test_performance_reporting.py
uv run pytest -m performance tests/performance/test_preparation.py
test -s .artifacts/performance-baseline.json
uv run ruff check tests/performance tests/test_performance_reporting.py
uv run ruff format --check tests/performance tests/test_performance_reporting.py
uv run mypy tests/performance tests/test_performance_reporting.py
```

Expected artifact: `.artifacts/performance-baseline.json` validates as JSON and
contains separate diff/preview preparation records and all three memory scopes.

### M1-S3 — Measure current `Static` rendering and viewer interactions

**Outcome:** the same report distinguishes preparation from the current
whole-document `Static` viewer's first frame and repeated viewport operations.

**Target paths**

- Add `tests/performance/viewer_harness.py` with the smallest headless Textual
  app that composes the production `CodeScroll` around one `Static`, applies
  either the production `DiffView.text` or preview `Syntax`, and exposes settled
  benchmark operations.
- Add `tests/performance/test_viewer.py`, marked `performance`, using the exact
  rendering matrix and operation counts in the workload contract.
- Extend `tests/test_performance_reporting.py` only if the renderer adds a new
  record field to the documented schema.

**Implementation notes**

1. Reuse `CodeScroll`, `JumpScrollBar`, `scrollbar_click_target`,
   `build_diff_view`, and preview `Syntax`; do not duplicate their behavior or
   instantiate the full `GitPaneApp` with mocked repository panels.
2. Build/prepare content before each rendering timer. Start first-render timing
   immediately before updating the mounted `Static` and stop only after
   `await pilot.pause()` has allowed the next headless frame. Record preparation
   separately rather than folding it into first render.
3. For interactions, execute the fixed count, await a settled frame after each
   action, and retain each sample. Use production unanimated page actions;
   bounded line scroll calls; targets at 10%, 50%, and 90% for repeated jump
   scrolling; positive and reset horizontal offsets; `pilot.resize_terminal()`;
   and the same `.wrapped` classes/`Syntax.word_wrap` mutation used by
   `GitPaneApp._set_wrapped`.
4. Before measuring an operation, place the viewport where it can actually move.
   Stable assertions must prove vertical/horizontal offsets or dimensions
   changed and remained bounded, and wrapping returned to its initial state;
   they must not assert a latency.
5. Use a fresh app per viewer/workload case at fixed 120x40, release references
   after each case, and collect garbage outside timers. Do not manually run the
   application and do not add browser/smoke steps.

**Dependencies:** M1-S1 generators and M1-S2 report fixture/schema.

**Verification**

```bash
uv run pytest -m performance tests/performance/test_viewer.py
uv run pytest -m performance
test -s .artifacts/performance-baseline.json
uv run ruff check tests/performance tests/test_performance_reporting.py
uv run ruff format --check tests/performance tests/test_performance_reporting.py
uv run mypy tests/performance tests/test_performance_reporting.py
```

Expected artifact: `.artifacts/performance-baseline.json` now contains separate
diff and preview first-render, line/page/jump/horizontal scroll, resize, and
wrap-toggle records in addition to Story 2's preparation and memory records.

### M1-S4 — Capture and document the reviewed baseline

**Outcome:** contributors have one command and a checked-in, revision-specific
baseline that later milestones can compare without treating local timings as
performance contracts.

**Target paths**

- Add `docs/performance-baseline.md` containing methodology, workload table,
  command, report schema/location, environment, source revision/dirty-state
  note, summarized measured results, interpretation, and comparison guidance.
- Modify `docs/milestones.md` only to update this status table as each story is
  accepted; status updates are separate small documentation commits under the
  workflow.

**Implementation notes**

1. Run the full performance command once from the repository root on an idle
   machine. Copy min/median/max timing and retained-byte summaries from the raw
   JSON; do not hand-time, round away units, omit slow results, or invent a pass
   threshold.
2. Keep diff and preview tables separate. Within each, separate parse/read,
   highlighting, view construction, first render, each interaction, wrapping,
   resize, active-document memory, and cache memory.
3. State limitations: `run_test` is headless, timings are machine-dependent,
   `tracemalloc` excludes native/process allocations, the preview loader retains
   its 1 MiB limit, and focused dense/long cases are not run at every size.
4. Describe the future comparison rule: same command, workload IDs, dimensions,
   terminal size, and environment fields; compare raw phase records, not only an
   end-to-end total. Preserve the raw report as an ignored local artifact rather
   than committing volatile JSON.
5. This is the final cleanup/documentation story. Do not alter `docs/perf.md`,
   redesign later milestones, optimize production code, or commit unrelated
   dirty-worktree changes.

**Dependencies:** M1-S1 through M1-S3 accepted and the complete raw artifact
generated from the revision being documented.

**Verification**

```bash
uv run ruff check gitpane tests
uv run ruff format --check gitpane tests
uv run mypy gitpane tests
uv run pytest -m "not performance"
uv run pytest -m performance
test -s .artifacts/performance-baseline.json
```

Expected checked-in artifact: `docs/performance-baseline.md`. Confirm its
revision, dirty-state note, workload IDs, environment, and result row counts
match `.artifacts/performance-baseline.json` before marking the story complete.

## Milestone 1 status

| Story | Status | Depends on | Primary deliverable |
| --- | --- | --- | --- |
| M1-S1 — Marker and workloads | Accepted | — | Registered marker and deterministic generators |
| M1-S2 — Preparation and memory | Accepted | M1-S1 | Raw report with isolated CPU/allocation phases |
| M1-S3 — Rendering and interaction | Accepted | M1-S1, M1-S2 | Headless current-viewer measurements |
| M1-S4 — Baseline documentation | Accepted | M1-S1–M1-S3 | `docs/performance-baseline.md` |

## Verification

```bash
uv run ruff check gitpane tests
uv run ruff format --check gitpane tests
uv run mypy gitpane tests
uv run pytest -m "not performance"
uv run pytest -m performance
```

# Milestone 2: Virtualized diff viewer

## Goal

Replace whole-document painting for unwrapped diffs with a read-only virtual
viewer whose rendering work is primarily proportional to the visible viewport.
The current diff appearance and navigation behavior must remain intact.

## Tasks

1. Implement a small `ScrollView`-based code viewer that stores styled logical
   lines, reports its virtual dimensions, and renders only requested rows.
2. Integrate the jump scrollbar and non-animated page actions directly into the
   viewer.
3. Change diff preparation to produce independently renderable styled rows
   while preserving markers, old/new line numbers, syntax colors, and complete
   add/remove backgrounds.
4. Migrate the unwrapped diff path from `VerticalScroll` plus one `Static` to
   the virtual viewer.
5. Preserve horizontal scrolling, initial scrolling to the first change,
   loading state, stale-request protection, theme colors, and file switching.
6. Add a bounded visible-line strip cache only if profiling shows it helps.
   Ensure document replacement and relevant viewport changes invalidate it.
7. Compare the result with the Milestone 1 baseline and document the outcome.

## Acceptance criteria

- Unwrapped diff painting does not render every document row on each viewport
  update.
- A 50,000-line prepared diff can be navigated without constructing one
  document-sized `Static` renderable.
- Diff text, gutters, row backgrounds, syntax styles, and first-change position
  match current behavior.
- Line/page scrolling and scrollbar track clicks remain unanimated and bounded.
- Replacing a document cannot display stale rows or cached strips.
- The benchmark shows a material improvement in large-diff first render or
  scrolling without a regression for small diffs.
- Ruff, formatting, mypy, and the full test suite pass.

## Scope and locked decisions

- Optimize only the **unwrapped diff** path. File previews remain
  `CodeScroll(Static(...))`, and wrapped diffs retain the current whole-document
  `Static` fallback. Milestone 3 owns preview virtualization; Milestone 4 owns a
  wrapped-row index if measurements justify one.
- Add one focused read-only `ScrollView` subclass. It stores an immutable
  sequence of independently styled Rich `Text` lines and a maximum cell width;
  it is not an editor, does not create one widget per line, and has no cursor,
  selection, or progressive-highlighting machinery.
- Keep complete-document syntax highlighting in the existing worker. This
  milestone changes prepared diff output from one joined `Text` to styled
  logical lines, but does not change lexing policy or parse Git output
  differently.
- Preserve the current row format exactly: marker, four-column old number,
  four-column new number, one separating space, source text, syntax foreground
  styles only on the new side, and `#142b1d` / `#351b20` backgrounds across the
  complete rendered add/remove row content. Empty rows, tabs, wide Unicode, and
  4,096-column benchmark rows must remain valid.
- The virtual viewer owns horizontal and vertical scrolling, the existing jump
  scrollbar behavior, and non-animated page actions. Do not put the virtual
  viewer inside another scroll container.
- Keep the existing wrapped-mode semantics: `w` is independent per tab,
  entering wrapped mode hides horizontal overflow and resets horizontal offset
  to zero, both wrap transitions restore relative vertical progress, and a diff
  loaded while wrapping is enabled is shown wrapped. Build the joined wrapped
  `Text` lazily; an unwrapped 50,000-row diff must never construct it.
- Applying a current diff replaces the document atomically, resets both offsets,
  then scrolls to `first_change` after dimensions are current. Index zero is a
  valid first change. Empty/context-only documents remain at the origin.
  Existing request tokens and exclusive workers remain the authority for stale
  request rejection; a rejected result must not mutate content, loading state,
  offsets, or viewer generation.
- Do **not** add a custom visible-strip cache initially. Textual's normal render
  cache plus viewport-only `render_line()` is the KISS implementation. Every
  document replacement must force a repaint and dimension update; horizontal
  scroll and resize must crop from current lines. If profiling still identifies
  line rendering as material, stop and update this plan before adding a small
  generation/row/x/width-keyed cache with bounded size and explicit invalidation
  on replacement, resize, style/theme change, and wrapping change.
- Keep the four-entry `build_diff_view` LRU policy unchanged. Milestone 3 owns
  cache-admission limits; this milestone may reduce each entry by removing the
  joined document renderable but must not introduce a global memory manager.
- Preserve workload IDs, operation counts, terminal size, and report schema from
  Milestone 1. Performance remains report-only in pytest. For milestone review,
  “material improvement” means the same-environment 50k `diff-mixed`
  first-render result is at least 2x faster than the M1 `Static` result, and “no
  small-diff regression” means the 1k `diff-mixed` first-render result is no more
  than 20% slower. Treat these as a human review gate, not a CI timing assertion;
  if environment fields differ, record the comparison as directional and rerun
  on the M1 environment before claiming acceptance.
- Do not boot the editor or add manual/browser smoke tests. Functional behavior
  belongs in normal headless tests; resource-intensive measurements remain
  marked `performance`.

## Acceptance-to-story mapping

| Acceptance criterion | Owning stories | Proof |
| --- | --- | --- |
| Viewport updates do not render every unwrapped row | M2-S2, M2-S3 | Instrumented `render_line()` headless tests request only visible/cropped rows; app composition uses the viewer directly. |
| A prepared 50k diff has no document-sized `Static` renderable in unwrapped mode | M2-S1, M2-S3, M2-S4 | Prepared output is per-line, the default app path never joins it, and the 50k harness exercises the production virtual viewer. |
| Text, gutters, backgrounds, syntax styles, and first-change position match | M2-S1, M2-S3 | Stable row-style unit tests plus app-level initial-position tests, including first change zero. |
| Line/page/jump/horizontal behavior is unanimated and bounded | M2-S2, M2-S3 | Viewer action, scrollbar, long-line cropping, and app integration tests. |
| Wrapping retains current behavior without expanding M2 scope | M2-S3 | Hybrid virtual-unwrapped / lazy-`Static`-wrapped tests cover both transitions, progress, horizontal reset, and load-while-wrapped. |
| Replacement cannot expose stale rows or strips | M2-S2, M2-S3 | Same-viewport replacement test plus stale-token app test proving no state/generation mutation. |
| Large-diff improvement and no small-diff regression | M2-S4, M2-S5 | Unchanged M1 workload contract, raw post-M2 report, and reviewed ratio table against `docs/performance-baseline.md`. |
| All quality gates pass and results are documented | M2-S5 | Full format, lint, type, normal, and performance commands plus final comparison document. |

## Story plan

### M2-S1 — Prepare independently renderable diff lines

**Outcome:** cached diff preparation returns immutable styled logical lines and
first-change metadata without constructing one joined document `Text`; the
existing `Static` display remains functional until integration is changed.

**Target paths**

- Modify `gitpane/app.py` (`DiffView`, `build_diff_view`, and diff-row rendering
  helpers only).
- Modify `tests/test_app.py` for the new prepared representation and row-level
  formatting/style contracts.
- Modify `tests/performance/test_preparation.py` to measure the same
  `view-construction` phase against per-line construction while retaining the M1
  workload IDs, phase name, samples, and memory scopes.

**Implementation guidance**

1. Make `DiffView` contain a tuple of styled `Text` lines and `first_change`.
   Keep a tiny explicit helper that joins lines with exactly one newline only
   for the temporary/required `Static` fallback; do not store that joined value
   in `DiffView` and do not memoize it.
2. Refactor the current single-pass `render_diff_rows()` behavior into one
   linear pass producing one `Text` per `Row`. Highlight the reconstructed new
   side once, advance its index only for rows with `new_no`, and copy/append Rich
   text without converting through markup.
3. Apply the add/remove background after gutter and source text are complete so
   it covers every character in that logical row without replacing syntax
   foreground colors. Preserve the exact plain strings and span semantics
   already asserted in `tests/test_app.py`.
4. Keep `build_diff_view(entry, patch)` and its four-entry cache key/behavior.
   Extend tests to prove repeated keys reuse the tuple, changed patch/entry
   rebuilds it, and a prepared multi-row view has no joined document field.
5. During this story only, let `apply_diff_view()` join the tuple before updating
   the existing `Static`; M2-S3 removes that join from the unwrapped path. Avoid
   unrelated app or CSS changes.

**Dependencies:** Milestone 1 accepted.

**Verification**

```bash
uv run pytest tests/test_app.py tests/test_diff.py
uv run pytest -m performance tests/performance/test_preparation.py
uv run ruff check gitpane/app.py tests/test_app.py tests/performance/test_preparation.py
uv run ruff format --check gitpane/app.py tests/test_app.py tests/performance/test_preparation.py
uv run mypy gitpane/app.py tests/test_app.py tests/performance/test_preparation.py
```

Expected: row text/styles and cache behavior are unchanged, preparation records
remain structurally comparable, and `DiffView` retains no joined full-document
renderable.

### M2-S2 — Add the minimal virtual code viewer

**Outcome:** a standalone `ScrollView` paints and horizontally crops only the
requested logical line, reports correct virtual dimensions, and owns current
page/jump behavior without a custom strip cache.

**Target paths**

- Add `gitpane/widgets/code_view.py` containing the virtual viewer and the shared
  jump-scrollbar primitives currently in `gitpane/app.py`.
- Modify `gitpane/widgets/__init__.py` to export the new production widgets and
  helper.
- Modify `gitpane/app.py` only to import/re-export the moved `CodeScroll`,
  `JumpScrollBar`, and `scrollbar_click_target`, preserving existing imports and
  preview behavior.
- Add `tests/test_code_view.py` for viewer-specific functional tests.
- Modify `tests/test_app.py` only where existing shared-scroll tests need to use
  the moved implementation.

**Implementation guidance**

1. Implement a small `CodeView(ScrollView)` with a tuple of `Text` lines, a
   monotonically increasing read-only document generation for testability, and
   one `set_document(lines)` method. That method replaces all content, bumps the
   generation even for equal-looking new input, computes maximum Rich cell width
   once, sets `virtual_size = Size(max_width, len(lines))`, resets offsets
   unanimated, and refreshes the widget.
2. Override `render_line(y)` using Textual/Rich strip APIs: select only the
   requested virtual row, render it without wrapping or markup interpretation,
   crop/pad it for the current horizontal offset and viewport width, and return
   a blank strip outside document bounds. Do not join neighboring rows and do
   not call a renderer over the complete tuple.
3. Override `vertical_scrollbar` with `JumpScrollBar` and keep page up/down
   actions as direct `animate=False` calls, matching `CodeScroll`. Preserve
   `scrollbar_click_target()` centering/clamping for zero and short dimensions.
4. Test empty/single/many-row dimensions; styled gutter/source/background spans;
   tabs and wide Unicode cell width; long-line horizontal crop and reset;
   bounded line/page/jump scrolling; resize; and replacement at the same scroll
   position. Instrument requested row numbers to prove a repaint of a large
   document does not touch all rows.
5. Add no custom `lru_cache`, strip dictionary, wrapping support, app-specific
   request logic, or preview logic.

**Dependencies:** M2-S1 prepared-line contract.

**Verification**

```bash
uv run pytest tests/test_code_view.py tests/test_app.py
uv run pytest -m "not performance"
uv run ruff check gitpane/widgets/code_view.py gitpane/widgets/__init__.py gitpane/app.py tests/test_code_view.py tests/test_app.py
uv run ruff format --check gitpane/widgets/code_view.py gitpane/widgets/__init__.py gitpane/app.py tests/test_code_view.py tests/test_app.py
uv run mypy gitpane/widgets/code_view.py gitpane/widgets/__init__.py gitpane/app.py tests/test_code_view.py tests/test_app.py
```

Expected: functional tests prove virtual dimensions and visible-row rendering,
including fresh content after replacement; normal tests still exercise the
unchanged `Static` app path and preview `CodeScroll`.

### M2-S3 — Integrate virtual unwrapped diffs and wrapped fallback

**Outcome:** the Changes tab uses `CodeView` directly in normal mode, lazily
switches to the old whole-document path only for wrapping, and preserves loading,
navigation, initial position, file replacement, and stale-request behavior.

**Target paths**

- Modify `gitpane/app.py` composition, wrap switching, refresh/reset helpers,
  request loading state, and current-result application for diffs only.
- Modify `gitpane/app.tcss` for the virtual viewer and hidden/shown wrapped
  fallback while retaining the locked palette and preview rules.
- Modify `tests/test_app.py` with headless integration coverage.
- Modify `tests/test_theme.py` for the new diff selectors and unchanged palette
  contracts.

**Implementation guidance**

1. Compose one unwrapped `CodeView` directly in `#diff-pane` and one initially
   hidden `CodeScroll(Static(...))` fallback for wrapped mode. Use unambiguous
   IDs (for example `#diff-view`, `#diff-scroll`, and `#diff`) and centralize
   selection of the active diff widget so loading/reset code cannot update the
   wrong one. Leave the preview composition untouched.
2. Store only the currently accepted `DiffView` on the app. In unwrapped mode,
   call `CodeView.set_document(view.lines)`, clear loading, and after dimensions
   settle scroll directly to `view.first_change` with `animate=False`. In wrapped
   mode, join the same lines only when applying/showing the fallback, apply the
   current wrapped CSS, and perform the same first-change positioning.
3. On `w`, capture progress from the active path, switch visibility, reset x to
   zero when entering wrapping, and restore relative y after the destination has
   laid out. On return to unwrapped mode, re-use prepared lines (not a split of
   the joined text), remove the joined value from the `Static`, and preserve the
   current behavior of leaving x at zero.
4. Status refresh/clear must empty both paths, cancel their loading indicators,
   reset offsets, and discard the accepted view. A new request may leave the
   prior content visible as today, but only the matching token may replace it.
   Add a regression test where an older result arrives after a newer one and
   assert content, generation, offsets, and loading state all remain those of
   the newer result.
5. Add headless tests for first changes at zero and after leading context,
   no-change and empty documents, repeated file replacement while scrolled,
   line/page/jump and long-line horizontal movement, both wrap
   transitions/progress restoration, and loading a new diff while already
   wrapped. Assert the default diff DOM has no document-sized `Static` content.

**Dependencies:** M2-S1 and M2-S2 accepted.

**Verification**

```bash
uv run pytest tests/test_app.py tests/test_code_view.py tests/test_theme.py
uv run pytest -m "not performance"
uv run ruff check gitpane/app.py tests/test_app.py tests/test_code_view.py tests/test_theme.py
uv run ruff format --check gitpane/app.py tests/test_app.py tests/test_code_view.py tests/test_theme.py
uv run mypy gitpane/app.py tests/test_app.py tests/test_code_view.py tests/test_theme.py
```

Expected: unwrapped app tests use `CodeView`, wrapped tests alone populate the
fallback `Static`, first-change scrolling is exact and unanimated, and stale
applications are state-preserving no-ops.

### M2-S4 — Benchmark the production virtual diff path

**Outcome:** the M1 harness measures the new diff viewer with the exact existing
matrix and demonstrates viewport-scaled work and reviewable 1k/50k comparison
data while previews continue to measure their unchanged `Static` path.

**Target paths**

- Modify `tests/performance/viewer_harness.py` to support the production virtual
  diff viewer and existing static preview viewer without duplicating scrolling
  behavior.
- Modify `tests/performance/test_viewer.py` to supply prepared diff lines to the
  virtual harness and retain every M1 workload ID, operation, count, assertion,
  and report key.
- Modify `tests/performance/test_preparation.py` only if final operation labels
  need alignment with the M1 comparison table.
- Modify `tests/test_performance_reporting.py` only if a required structural
  report assertion changes; do not bump the schema for implementation details.

**Implementation guidance**

1. Keep one small harness with an explicit viewer mode. Diff cases mount
   `CodeView`; preview cases continue to mount `CodeScroll(Static)`. Reuse each
   widget's production page action and scrollbar rather than simulating them in
   a benchmark-only class.
2. Start first-render timing immediately before `set_document()` for diffs (or
   `Static.update()` for previews) and stop after the same settled headless frame.
   Preparation remains outside this timer.
3. Preserve ten line scrolls, ten page scrolls, five 10%/50%/90% jumps, five
   horizontal samples where applicable, two resizes, wrap on/off, fixed 120x40,
   and all structural bounds assertions. For diff wrap measurements, exercise
   the production lazy fallback transition rather than pretending `CodeView`
   supports wrapping.
4. Add a stable assertion/counter showing the 50k unwrapped first frame and each
   scroll render only a viewport-sized set of rows. Never assert elapsed time in
   pytest.
5. Run the full performance command on an idle machine matching the M1
   environment. Retain `.artifacts/performance-baseline.json` locally for M2-S5;
   do not edit documentation or commit raw JSON in this story. If the review
   ratios miss the locked gate, profile before changing code; do not add a strip
   cache without a plan update.

**Dependencies:** M2-S3 accepted; M1 workload/report contract.

**Verification**

```bash
uv run pytest tests/test_performance_reporting.py
uv run pytest -m performance tests/performance/test_preparation.py tests/performance/test_viewer.py
uv run pytest -m performance
test -s .artifacts/performance-baseline.json
uv run ruff check tests/performance tests/test_performance_reporting.py
uv run ruff format --check tests/performance tests/test_performance_reporting.py
uv run mypy tests/performance tests/test_performance_reporting.py
```

Expected: the raw report still contains separate diff/preview preparation,
first-render, line/page/jump/horizontal, resize, wrap, and memory records; diff
records use the virtual path and preview records remain directly comparable to
M1.

### M2-S5 — Final cleanup and reviewed comparison

**Outcome:** obsolete unwrapped-`Static` glue is removed, all gates pass, and a
revision/environment-specific document records the M2 result against M1 without
rewriting the original baseline.

**Target paths**

- Modify `gitpane/app.py` and `gitpane/app.tcss` only if M2-S4 exposes dead
  transitional names/branches; do not refactor unrelated app behavior.
- Modify `tests/test_app.py`, `tests/test_code_view.py`, `tests/test_theme.py`,
  `tests/performance/viewer_harness.py`, and `tests/performance/test_viewer.py`
  only where required by that cleanup; otherwise leave them unchanged.
- Add `docs/performance-m2.md` with source revision and dirty state, environment,
  unchanged workload contract, selected raw M2 results, exact M1 values and
  ratios, viewport-rendering evidence, memory observations, limitations, and the
  locked acceptance-gate conclusion.
- Modify `docs/milestones.md` only to update the Milestone 2 status table after
  each accepted story; these remain separate small documentation updates under
  the workflow.

**Implementation guidance**

1. Remove compatibility code that is no longer used by either the wrapped diff
   fallback or static preview. Keep `CodeScroll` for those two paths and keep
   public imports used by tests unless all callers are updated in scope.
2. Generate the final raw report from the exact revision being documented on an
   idle M1-compatible machine. Copy integer min/median/max values; report ratios
   for 1k and 50k `diff-mixed` first render and the individual diff scroll
   operations. Do not hide preparation/highlighting, wrapped fallback, preview,
   or memory results that did not improve.
3. State explicitly whether the 2x large-diff and 20% small-diff review gates
   passed. Keep timing gates out of tests, retain raw JSON only under ignored
   `.artifacts/`, and leave `docs/performance-baseline.md` unchanged as the M1
   source of record.
4. This is the only phase-summary/documentation story. Do not edit
   `docs/perf.md`, redesign Milestones 3/4, change full-context Git behavior, add
   cache admission, or include unrelated worktree changes.

**Dependencies:** M2-S1 through M2-S4 accepted and the final raw artifact
generated from the documented revision.

**Verification**

```bash
uv run ruff check gitpane tests
uv run ruff format --check gitpane tests
uv run mypy gitpane tests
uv run pytest -m "not performance"
uv run pytest -m performance
test -s .artifacts/performance-baseline.json
```

Expected checked-in documentation: `docs/performance-m2.md`. Confirm its source
revision, dirty-state note, environment, workload IDs, result values, ratios, and
gate conclusion match the final raw report and the M1 values in
`docs/performance-baseline.md` before accepting the milestone.

## Milestone 2 status

| Story | Status | Depends on | Primary deliverable |
| --- | --- | --- | --- |
| M2-S1 — Prepared diff lines | Accepted | M1 | Immutable independently styled rows |
| M2-S2 — Virtual code viewer | Accepted | M2-S1 | Viewport-only `ScrollView` with current navigation |
| M2-S3 — Diff integration | Planned | M2-S1, M2-S2 | Virtual unwrapped path and lazy wrapped fallback |
| M2-S4 — Benchmark migration | Planned | M2-S3 | M1-compatible post-virtualization raw report |
| M2-S5 — Cleanup and comparison | Planned | M2-S1–M2-S4 | `docs/performance-m2.md` and accepted status |

## Verification

```bash
uv run ruff check gitpane tests
uv run ruff format --check gitpane tests
uv run mypy gitpane tests
uv run pytest -m "not performance"
uv run pytest -m performance
```

# Milestone 3: Shared preview and resource guardrails

## Goal

Apply viewport-scaled rendering to file previews and bound the remaining
large-document costs demonstrated by measurements. Prefer the same focused
viewer used by diffs unless a measured `TextArea` prototype is clearly simpler
or faster.

## Tasks

1. Compare the shared virtual viewer with a read-only Textual `TextArea` for
   preview startup, scrolling, syntax coverage, wrapping, and implementation
   complexity.
2. Migrate previews to the smallest option that preserves line numbers, syntax
   highlighting, horizontal scrolling, loading state, and stale-request
   protection.
3. Profile syntax highlighting after virtualization. If it remains a material
   delay, add a measured plain-text fallback for very large documents.
4. Prevent oversized diff views from occupying the four-entry LRU cache merely
   because the entry count is below its limit. Use a simple row- or byte-based
   admission rule selected from measurements.
5. Add a practical maximum-line-length guard if the long-line benchmark shows a
   meaningful worst case.
6. Preserve the existing 1 MiB preview input limit unless measurements and a
   separate product decision support changing it.
7. Re-run and record the complete benchmark for both viewers.

## Acceptance criteria

- Diff and preview scrolling both use a viewport-scaled rendering path in
  unwrapped mode.
- Preview line numbers, syntax colors, horizontal scrolling, and error messages
  retain their current behavior.
- Large documents cannot cause unbounded retention through the diff view cache.
- Any highlighting fallback has a documented, measured threshold and a clear
  user-visible indication that highlighting was omitted.
- Extreme line lengths are either handled efficiently or rejected with a clear
  bounded policy.
- The benchmark shows no material small-file regression and improved large-file
  behavior for both viewers.
- Ruff, formatting, mypy, and the full test suite pass.

## Verification

```bash
uv run ruff check gitpane tests
uv run ruff format --check gitpane tests
uv run mypy gitpane tests
uv run pytest -m "not performance"
uv run pytest -m performance
```

# Milestone 4: Wrapped-mode optimization

## Goal

Remove the remaining whole-document wrapped rendering path if measurements or
real usage show it is a significant problem. This milestone is gated: do not
implement it if wrapped large-file performance is already acceptable after the
first three milestones.

## Entry criteria

- The post-Milestone 3 benchmark identifies wrapped layout, painting, resize, or
  wrap toggling as a material bottleneck; or
- user reports show that large-file wrapping is a common workflow and remains
  noticeably slow.

## Tasks

1. Build a width-dependent index mapping visual rows to logical lines and
   wrapped sections.
2. Cache wrapping metadata for the active document and viewport width without
   pre-rendering the complete document into one Rich renderable.
3. Invalidate the mapping on document replacement, relevant style changes, and
   width changes.
4. Preserve relative vertical position when wrapping is toggled and keep the
   initial diff position aligned with the first changed logical row.
5. Cover empty lines, tabs, wide Unicode cells, very long lines, resize, and
   repeated wrap toggles in functional tests.
6. Compare wrapped and unwrapped results with all earlier baselines.

## Acceptance criteria

- Wrapped rendering no longer requires a document-sized `Static`.
- Visual-row lookup and painting scale with the viewport after wrapping metadata
  has been prepared.
- Resize and wrap toggles cannot use stale width-dependent mappings.
- Diff styling, preview line numbers, horizontal-scroll suppression, and
  relative-position restoration remain correct.
- The measured improvement justifies the added indexing complexity.
- Ruff, formatting, mypy, and the full test suite pass.

## Verification

```bash
uv run ruff check gitpane tests
uv run ruff format --check gitpane tests
uv run mypy gitpane tests
uv run pytest -m "not performance"
uv run pytest -m performance
```

# Deferred product decisions

These ideas may outperform renderer-level tuning but change behavior and are not
part of the milestones above:

- Add a changed-hunks/full-file toggle instead of always requesting `-U9999`.
- Disable wrapping above a large-document threshold.
- Add progressive, viewport-prioritized syntax highlighting.

Evaluate them only after the benchmark distinguishes renderer, highlighting,
and full-context costs.
