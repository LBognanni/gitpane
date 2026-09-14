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
