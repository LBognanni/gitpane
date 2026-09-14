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
