# UI performance

## Problem

Scrolling and opening large diffs or file previews becomes slow because both code
viewers render the entire document through a single Textual `Static`:

- The diff viewer is `CodeScroll(Static(id="diff"))`.
- The file preview is `CodeScroll(Static(id="preview"))`.
- Diff rendering creates one large Rich `Text` containing every row and all of
  its style spans.
- Syntax highlighting reconstructs and highlights the complete new side before
  anything is displayed.
- Git is called with `-U9999`, so even a small change can produce a complete
  large-file diff.

Diff loading and highlighting already run in worker threads. This prevents them
from directly blocking the event loop, but it does not reduce the time before a
document appears, retained memory, or the amount of document state involved in
painting and layout.

## Baseline observations

A synthetic Textual `run_test` benchmark using 20,000 lines of approximately
106 columns produced these initial-mount times on one development machine:

| Viewer | Initial mount |
| --- | ---: |
| `VerticalScroll` containing one `Static` | approximately 1.92 seconds |
| Textual `RichLog` | approximately 0.94 seconds |
| Minimal virtual `ScrollView` prototype | approximately 0.06 seconds |

In a separate historical synthetic test, `render_diff_rows` took approximately
5.4 seconds to prepare 50,000 highlighted Python rows and generated roughly
400,000 Rich style spans.

These numbers are directional rather than performance contracts. The benchmark
was synthetic, `run_test` adds overhead, and results depend on the machine,
terminal, Textual version, lexer, line lengths, and style density. They are
enough to identify whole-document rendering and highlighting as the first paths
to measure and improve.

## Goals

- Keep scrolling cost primarily proportional to the visible viewport rather
  than total document length.
- Preserve the current diff gutter, add/remove backgrounds, syntax colors,
  horizontal scrolling, jump scrollbar, paging, and initial first-change jump.
- Improve time to first display and bound retained memory for very large files.
- Use one viewer implementation for diffs and previews where practical.
- Preserve responsive file switching and discard stale worker results.

## Non-goals

- One Textual widget per source line. Thousands of DOM nodes would replace one
  scaling problem with another.
- Editing, cursor movement, selections, or other text-editor behavior.
- Side-by-side diffs or partial staging.
- Progressive highlighting until simpler approaches have been measured.
- Changing full-file context without an explicit product decision.

## Recommended architecture

Create a read-only code viewer based on Textual's `ScrollView`.

The viewer stores logical styled lines and the maximum line width. Its virtual
height is the number of visual rows, and `render_line()` renders and crops only
the requested visible row. A small cache may retain recently rendered strips,
keyed by row, horizontal offset, viewport width, and document generation.

This design keeps the current custom presentation while avoiding a complete
document-sized `Static`. It also lets the viewer own the existing jump
scrollbar and non-animated page actions instead of wrapping another widget in a
scroll container.

The document supplied to the viewer should contain enough information to:

- return a styled logical line;
- report logical line count and maximum cell width;
- map a diff row to its initial scroll position;
- invalidate cached strips when content, width, theme, or wrapping changes.

Keep this model small. It does not need to become a general editor or document
framework.

## Syntax highlighting

Viewport virtualization fixes painting and layout but does not by itself remove
the up-front cost of lexing and constructing style spans. The options, in
increasing implementation complexity, are:

1. Highlight the complete document in the existing worker, then display it in
   the virtual viewer. This is the recommended first implementation.
2. Render very large documents without syntax highlighting. Select the cutoff
   from measured line count, byte size, style count, and latency rather than an
   arbitrary constant.
3. Show plain rows immediately and highlight chunks around the viewport. This
   gives the best time to first display but introduces scheduling, cache
   invalidation, and stale-result complexity.

Start with complete worker highlighting. Add a plain-text fallback only if the
post-virtualization benchmark shows that highlighting remains a material wait.
Defer progressive highlighting unless real usage justifies it.

## Wrapping

Unwrapped documents have a direct mapping from one logical line to one visual
row and should be optimized first. Wrapped documents require a width-dependent
index from visual rows back to logical lines.

The first virtual viewer may retain the current whole-document rendering path
for wrapped mode if necessary. Measure that fallback before implementing a
wrapped-row index. If wrapped large files are common or the fallback remains
slow, build and cache the index for the current viewport width and invalidate it
on resize or document replacement.

Disabling wrapping for large documents is an acceptable simpler alternative,
but it is a user-visible behavior change and should be made deliberately.

## Preview options

Textual's read-only `TextArea` is already virtualized and is worth comparing for
plain file previews. It is less suitable for diffs because GitPane needs two
line-number columns and complete-row add/remove backgrounds. A shared custom
viewer is preferred if it stays small and can preserve preview syntax support.

`RichLog` is also virtualized during scrolling, but it eagerly converts a whole
renderable into stored strips and does not naturally rebuild when wrapping is
toggled. It improves on `Static` but offers less control than a focused viewer.

## Memory and worst cases

- The four-entry `build_diff_view` LRU cache can retain several large patch
  strings, rendered text values, and their style spans. Large views should not
  be cached solely because the entry-count limit has not been reached.
- Bound cache admission by measured bytes or rows, or cache a smaller prepared
  representation. Avoid a complex global memory manager.
- Protect against extreme line lengths. One generated multi-megabyte line can
  be more expensive than many ordinary lines and can inflate virtual width and
  rendering work.
- Keep the existing preview byte limit unless measurements support changing it.
- Preserve cancellation tokens and exclusive workers so superseded documents
  are never applied to the UI.

## Product-level option

Full context is currently requested with `-U9999`. A changed-hunks/full-file
toggle would avoid most work for large files and may have greater impact than
renderer tuning. It also changes GitPane's full-file review workflow, so it is
not part of the initial performance work.

## Measurement strategy

Add a repeatable benchmark or profiling harness for 1,000 and 10,000 line
documents. Include ordinary source, focused dense syntax styles and long lines,
additions and removals, and both diff and preview content.

Record at least:

- parse and syntax-highlight duration;
- prepared-view construction duration;
- time from applying a view to first rendered frame;
- repeated line, page, and scrollbar-jump latency;
- resize and wrap-toggle latency;
- retained memory for the active document and diff cache.

Keep benchmark assertions broad or report-only unless they are stable in CI.
Functional tests should verify visible-line rendering, scrolling bounds,
styling, cache invalidation, and first-change positioning without relying on
machine-specific timing.

All pytest benchmarks, timing checks, and other resource-intensive performance
workloads must use `@pytest.mark.performance`, with the marker registered in
`pyproject.toml`. Routine feature work runs
`uv run pytest -m "not performance"`; performance work runs the isolated suite
explicitly with `uv run pytest -m performance`. Functional correctness tests
for viewer behavior remain unmarked so they continue to run during ordinary
feature development.

## Implementation order

1. Establish the benchmark and profile the current implementation.
2. Add the virtual viewer and migrate the unwrapped diff path.
3. Reuse the viewer for previews and address measured highlighting and cache
   worst cases.
4. Optimize wrapped mode only if the benchmark and real usage justify it.
