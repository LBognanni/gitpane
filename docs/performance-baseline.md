# Performance baseline

This is the reviewed baseline for the current whole-document `Static` viewers. It
is a revision-specific comparison reference, not a timing contract or a pass/fail
threshold.

## Run and report

From the repository root, run the complete benchmark:

```bash
uv run pytest -m performance
```

The command uses deterministic in-memory inputs, does not invoke Git in timed
workloads, and exercises the production viewer pieces with Textual's headless
`run_test` at a fixed 120x40 terminal. It writes the volatile raw report to
`.artifacts/performance-baseline.json`. That directory is ignored: retain a raw
report locally for a comparison, but do not commit machine-specific JSON.

The report uses schema version 1. Each of its 123 records (62 diff and 61 preview)
contains the comparison keys `schema_version`, `viewer`, `workload_id`,
`line_count`, `phase`, `operation`, `unit`, raw integer `samples`, and integer
`min`, `median`, and `max`. Memory records also identify their allocation label,
peak, and cache information where applicable. Timings are nanoseconds; memory
summaries are retained bytes. The raw samples are the authoritative detail.

## Captured source and environment

This report was generated on an idle machine from commit
`495553f200d5ceb771ae47c37cb8cad11aa0e259`. The worktree was **clean** when the report
started. Timestamp: `2026-09-14T21:01:30.200183Z`.

| Field | Value |
| --- | --- |
| Python | CPython 3.12.3 |
| Platform | Linux-6.17.0-23-generic-x86_64-with-glibc2.39 |
| CPU | x86_64 (16 logical CPUs) |
| Total memory | 50429603840 bytes |
| Rich / Textual / unidiff | 15.0.0 / 8.2.8 / 1.0.0 |
| Terminal | 120 columns x 40 lines |

## Workloads

“1k”, “10k”, and “50k” below mean exactly 1,000, 10,000, and 50,000 source rows
for previews and parsed rows for diffs. Preparation covers every listed workload;
headless viewer operations cover all normal/mixed sizes plus the focused 1k dense
and long cases.

| Viewer | ID | Rows | Shape |
| --- | --- | --- | --- |
| diff | diff-mixed | 1000 | Unified patch with repeating context/remove/add groups. |
| diff | diff-mixed | 10000 | Unified patch with repeating context/remove/add groups. |
| diff | diff-mixed | 50000 | Unified patch with repeating context/remove/add groups. |
| diff | diff-dense | 1000 | Mixed diff with dense Python on the new side. |
| diff | diff-dense | 10000 | Mixed diff with dense Python on the new side. |
| diff | diff-long | 1000 | Mixed diff with 4,096-column changed and context rows. |
| preview | preview-normal | 1000 | Numbered Python assignments; representative source. |
| preview | preview-normal | 10000 | Numbered Python assignments; representative source. |
| preview | preview-normal | 50000 | Numbered Python assignments; representative source. |
| preview | preview-dense | 1000 | Compact Python with dense syntax spans. |
| preview | preview-dense | 10000 | Compact Python with dense syntax spans. |
| preview | preview-long | 1000 | Ordinary rows plus deterministic 4,096-column rows. |

## Measured results

Values below are copied from the raw report without unit conversion. A one-sample
row necessarily has identical min, median, and max. `complete-sequence` is shown
for context only; compare the individual phase and operation records.

### Diff

#### Parse, highlighting, view construction, and preparation total

| Workload | Rows | Phase | Operation | Samples | Min (ns) | Median (ns) | Max (ns) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| diff-mixed | 1000 | parse | diff.parse | 3 | 2084101 | 2090533 | 2132333 |
| diff-mixed | 1000 | highlight | highlight_new_lines | 3 | 44249755 | 44365795 | 44700471 |
| diff-mixed | 1000 | view-construction | render_diff_rows | 3 | 6136804 | 6291308 | 6990457 |
| diff-mixed | 1000 | prepare-total | build_diff_view | 3 | 51540883 | 51964498 | 53732989 |
| diff-mixed | 10000 | parse | diff.parse | 1 | 23385628 | 23385628 | 23385628 |
| diff-mixed | 10000 | highlight | highlight_new_lines | 1 | 490998238 | 490998238 | 490998238 |
| diff-mixed | 10000 | view-construction | render_diff_rows | 1 | 61908037 | 61908037 | 61908037 |
| diff-mixed | 10000 | prepare-total | build_diff_view | 1 | 633213443 | 633213443 | 633213443 |
| diff-mixed | 50000 | parse | diff.parse | 1 | 132390571 | 132390571 | 132390571 |
| diff-mixed | 50000 | highlight | highlight_new_lines | 1 | 2709141923 | 2709141923 | 2709141923 |
| diff-mixed | 50000 | view-construction | render_diff_rows | 1 | 463089051 | 463089051 | 463089051 |
| diff-mixed | 50000 | prepare-total | build_diff_view | 1 | 3260627303 | 3260627303 | 3260627303 |
| diff-dense | 1000 | parse | diff.parse | 3 | 1957471 | 1985394 | 2127233 |
| diff-dense | 1000 | highlight | highlight_new_lines | 3 | 137759415 | 143846625 | 161999428 |
| diff-dense | 1000 | view-construction | render_diff_rows | 3 | 12771394 | 12907654 | 13122702 |
| diff-dense | 1000 | prepare-total | build_diff_view | 3 | 153789343 | 165897877 | 180782297 |
| diff-dense | 10000 | parse | diff.parse | 1 | 27306581 | 27306581 | 27306581 |
| diff-dense | 10000 | highlight | highlight_new_lines | 1 | 1790875955 | 1790875955 | 1790875955 |
| diff-dense | 10000 | view-construction | render_diff_rows | 1 | 188939431 | 188939431 | 188939431 |
| diff-dense | 10000 | prepare-total | build_diff_view | 1 | 1926001582 | 1926001582 | 1926001582 |
| diff-long | 1000 | parse | diff.parse | 3 | 7888413 | 7906217 | 14830358 |
| diff-long | 1000 | highlight | highlight_new_lines | 3 | 66010524 | 68213792 | 70030074 |
| diff-long | 1000 | view-construction | render_diff_rows | 3 | 8005696 | 8039861 | 8793694 |
| diff-long | 1000 | prepare-total | build_diff_view | 3 | 84567134 | 85224323 | 86486813 |

#### First render and interactions

| Workload | Rows | Phase | Operation | Samples | Min (ns) | Median (ns) | Max (ns) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| diff-mixed | 1000 | viewer | first-render | 1 | 194072717 | 194072717 | 194072717 |
| diff-mixed | 1000 | viewer | line-scroll | 10 | 41227507 | 42178856 | 42833970 |
| diff-mixed | 1000 | viewer | page-scroll | 10 | 41182211 | 41765410 | 44171793 |
| diff-mixed | 1000 | viewer | jump-scroll | 5 | 41451493 | 42139099 | 42742577 |
| diff-mixed | 1000 | viewer | resize | 2 | 81896213 | 82611061 | 82611061 |
| diff-mixed | 1000 | viewer | wrap-toggle | 2 | 165007584 | 177879609 | 177879609 |
| diff-mixed | 1000 | viewer | complete-sequence | 1 | 1857757099 | 1857757099 | 1857757099 |
| diff-mixed | 10000 | viewer | first-render | 1 | 1727594010 | 1727594010 | 1727594010 |
| diff-mixed | 10000 | viewer | line-scroll | 10 | 41348507 | 42404184 | 43057135 |
| diff-mixed | 10000 | viewer | page-scroll | 10 | 41244249 | 41622458 | 42519493 |
| diff-mixed | 10000 | viewer | jump-scroll | 5 | 41255861 | 41864909 | 42516487 |
| diff-mixed | 10000 | viewer | resize | 2 | 63251697 | 83366748 | 83366748 |
| diff-mixed | 10000 | viewer | wrap-toggle | 2 | 1083415357 | 1275806578 | 1275806578 |
| diff-mixed | 10000 | viewer | complete-sequence | 1 | 5389557036 | 5389557036 | 5389557036 |
| diff-mixed | 50000 | viewer | first-render | 1 | 8373255651 | 8373255651 | 8373255651 |
| diff-mixed | 50000 | viewer | line-scroll | 10 | 41590758 | 42435674 | 43966352 |
| diff-mixed | 50000 | viewer | page-scroll | 10 | 41320714 | 41615404 | 42117940 |
| diff-mixed | 50000 | viewer | jump-scroll | 5 | 41526035 | 41671080 | 43123510 |
| diff-mixed | 50000 | viewer | resize | 2 | 62658189 | 81927472 | 81927472 |
| diff-mixed | 50000 | viewer | wrap-toggle | 2 | 5651417986 | 5819758150 | 5819758150 |
| diff-mixed | 50000 | viewer | complete-sequence | 1 | 21147472333 | 21147472333 | 21147472333 |
| diff-dense | 1000 | viewer | first-render | 1 | 489147645 | 489147645 | 489147645 |
| diff-dense | 1000 | viewer | line-scroll | 10 | 41415976 | 42416978 | 44100998 |
| diff-dense | 1000 | viewer | page-scroll | 10 | 41370759 | 42091450 | 43137718 |
| diff-dense | 1000 | viewer | jump-scroll | 5 | 41224952 | 42370520 | 42466201 |
| diff-dense | 1000 | viewer | resize | 2 | 83383469 | 83483669 | 83483669 |
| diff-dense | 1000 | viewer | wrap-toggle | 2 | 302737584 | 329437780 | 329437780 |
| diff-dense | 1000 | viewer | complete-sequence | 1 | 2446051552 | 2446051552 | 2446051552 |
| diff-long | 1000 | viewer | first-render | 1 | 277028261 | 277028261 | 277028261 |
| diff-long | 1000 | viewer | line-scroll | 10 | 41340211 | 42451764 | 42927478 |
| diff-long | 1000 | viewer | page-scroll | 10 | 41119612 | 42033198 | 42750822 |
| diff-long | 1000 | viewer | jump-scroll | 5 | 41417699 | 42111237 | 43679397 |
| diff-long | 1000 | viewer | horizontal-scroll | 5 | 41628499 | 41885247 | 42610686 |
| diff-long | 1000 | viewer | resize | 2 | 62600649 | 132717784 | 132717784 |
| diff-long | 1000 | viewer | wrap-toggle | 2 | 395304125 | 2370572034 | 2370572034 |
| diff-long | 1000 | viewer | complete-sequence | 1 | 4813725938 | 4813725938 | 4813725938 |

#### Active-document and cache memory

| Workload | Rows | Scope | Samples | Min retained (bytes) | Median retained (bytes) | Max retained (bytes) | Peak (bytes) | Cache entries |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| diff-mixed | 50000 | active-prepared-diff | 1 | 40475030 | 40475030 | 40475030 | 87676326 | 1 |
| diff-mixed | 50000 | four-entry-diff-cache | 1 | 166041030 | 166041030 | 166041030 | 213242342 | 4 |

The active diff measurement is one prepared 50k `diff-mixed` document. The cache
measurement is four distinct prepared 50k `diff-mixed` patches; its report cache
state is 4 entries, 0 hits, 4 misses, and maximum size 4.

### Preview

#### Read, highlighting, view construction, and preparation total

| Workload | Rows | Phase | Operation | Samples | Min (ns) | Median (ns) | Max (ns) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| preview-normal | 1000 | read-prepare | load_preview_view | 3 | 764674 | 774872 | 876005 |
| preview-normal | 1000 | highlight | Syntax.highlight | 3 | 45128525 | 48843876 | 49471539 |
| preview-normal | 1000 | view-construction | PreviewView | 3 | 12012 | 12493 | 13075 |
| preview-normal | 1000 | prepare-total | load_preview_view + Syntax.highlight + PreviewView | 3 | 47452302 | 47980395 | 48550950 |
| preview-normal | 10000 | read-prepare | load_preview_view | 1 | 1029357 | 1029357 | 1029357 |
| preview-normal | 10000 | highlight | Syntax.highlight | 1 | 469943547 | 469943547 | 469943547 |
| preview-normal | 10000 | view-construction | PreviewView | 1 | 12314 | 12314 | 12314 |
| preview-normal | 10000 | prepare-total | load_preview_view + Syntax.highlight + PreviewView | 1 | 466543144 | 466543144 | 466543144 |
| preview-normal | 50000 | read-prepare | load_preview_view | 1 | 1078761 | 1078761 | 1078761 |
| preview-normal | 50000 | highlight | Syntax.highlight | 1 | 2511324254 | 2511324254 | 2511324254 |
| preview-normal | 50000 | view-construction | PreviewView | 1 | 10981 | 10981 | 10981 |
| preview-normal | 50000 | prepare-total | load_preview_view + Syntax.highlight + PreviewView | 1 | 2510596299 | 2510596299 | 2510596299 |
| preview-dense | 1000 | read-prepare | load_preview_view | 3 | 803827 | 806152 | 861017 |
| preview-dense | 1000 | highlight | Syntax.highlight | 3 | 169589763 | 175649721 | 176123121 |
| preview-dense | 1000 | view-construction | PreviewView | 3 | 10550 | 11452 | 17343 |
| preview-dense | 1000 | prepare-total | load_preview_view + Syntax.highlight + PreviewView | 3 | 169951752 | 185909141 | 197911544 |
| preview-dense | 10000 | read-prepare | load_preview_view | 1 | 990953 | 990953 | 990953 |
| preview-dense | 10000 | highlight | Syntax.highlight | 1 | 1810698624 | 1810698624 | 1810698624 |
| preview-dense | 10000 | view-construction | PreviewView | 1 | 12554 | 12554 | 12554 |
| preview-dense | 10000 | prepare-total | load_preview_view + Syntax.highlight + PreviewView | 1 | 1852999613 | 1852999613 | 1852999613 |
| preview-long | 1000 | read-prepare | load_preview_view | 3 | 943483 | 986344 | 1042451 |
| preview-long | 1000 | highlight | Syntax.highlight | 3 | 48351109 | 48888561 | 49697899 |
| preview-long | 1000 | view-construction | PreviewView | 3 | 11482 | 11682 | 12263 |
| preview-long | 1000 | prepare-total | load_preview_view + Syntax.highlight + PreviewView | 3 | 50303209 | 51097680 | 52090656 |

#### First render and interactions

| Workload | Rows | Phase | Operation | Samples | Min (ns) | Median (ns) | Max (ns) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| preview-normal | 1000 | viewer | first-render | 1 | 368816473 | 368816473 | 368816473 |
| preview-normal | 1000 | viewer | line-scroll | 10 | 41101118 | 42316689 | 43217771 |
| preview-normal | 1000 | viewer | page-scroll | 10 | 40989596 | 42168276 | 66174142 |
| preview-normal | 1000 | viewer | jump-scroll | 5 | 41507902 | 42071242 | 44266754 |
| preview-normal | 1000 | viewer | resize | 2 | 62823204 | 82665086 | 82665086 |
| preview-normal | 1000 | viewer | wrap-toggle | 2 | 392763988 | 539280011 | 539280011 |
| preview-normal | 1000 | viewer | complete-sequence | 1 | 2630512508 | 2630512508 | 2630512508 |
| preview-normal | 10000 | viewer | first-render | 1 | 3854606574 | 3854606574 | 3854606574 |
| preview-normal | 10000 | viewer | line-scroll | 10 | 41421197 | 42611188 | 43768126 |
| preview-normal | 10000 | viewer | page-scroll | 10 | 41196599 | 41824363 | 44188255 |
| preview-normal | 10000 | viewer | jump-scroll | 5 | 41718622 | 42003924 | 43827901 |
| preview-normal | 10000 | viewer | resize | 2 | 64794760 | 82357801 | 82357801 |
| preview-normal | 10000 | viewer | wrap-toggle | 2 | 4156081105 | 5897211849 | 5897211849 |
| preview-normal | 10000 | viewer | complete-sequence | 1 | 15218477959 | 15218477959 | 15218477959 |
| preview-normal | 50000 | viewer | first-render | 1 | 19909551144 | 19909551144 | 19909551144 |
| preview-normal | 50000 | viewer | line-scroll | 10 | 41073465 | 42376111 | 43027268 |
| preview-normal | 50000 | viewer | page-scroll | 10 | 41196089 | 41881752 | 42184406 |
| preview-normal | 50000 | viewer | jump-scroll | 5 | 41637106 | 41826957 | 43215296 |
| preview-normal | 50000 | viewer | resize | 2 | 82343925 | 112648131 | 112648131 |
| preview-normal | 50000 | viewer | wrap-toggle | 2 | 20405141051 | 30132756159 | 30132756159 |
| preview-normal | 50000 | viewer | complete-sequence | 1 | 71797271796 | 71797271796 | 71797271796 |
| preview-dense | 1000 | viewer | first-render | 1 | 1121132096 | 1121132096 | 1121132096 |
| preview-dense | 1000 | viewer | line-scroll | 10 | 41573214 | 42516146 | 43612981 |
| preview-dense | 1000 | viewer | page-scroll | 10 | 41495096 | 41877482 | 77007401 |
| preview-dense | 1000 | viewer | jump-scroll | 5 | 41313611 | 42247847 | 42464969 |
| preview-dense | 1000 | viewer | resize | 2 | 63028813 | 83524457 | 83524457 |
| preview-dense | 1000 | viewer | wrap-toggle | 2 | 1187333929 | 1422947639 | 1422947639 |
| preview-dense | 1000 | viewer | complete-sequence | 1 | 5073980810 | 5073980810 | 5073980810 |
| preview-long | 1000 | viewer | first-render | 1 | 445442122 | 445442122 | 445442122 |
| preview-long | 1000 | viewer | line-scroll | 10 | 41414253 | 42851143 | 43439211 |
| preview-long | 1000 | viewer | page-scroll | 10 | 41239901 | 42011307 | 76518391 |
| preview-long | 1000 | viewer | jump-scroll | 5 | 41298131 | 42209113 | 42347566 |
| preview-long | 1000 | viewer | horizontal-scroll | 5 | 41621216 | 41748538 | 41961382 |
| preview-long | 1000 | viewer | resize | 2 | 63442620 | 64299077 | 64299077 |
| preview-long | 1000 | viewer | wrap-toggle | 2 | 447970567 | 991273874 | 991273874 |
| preview-long | 1000 | viewer | complete-sequence | 1 | 3624362207 | 3624362207 | 3624362207 |

#### Active-document memory

| Workload | Rows | Scope | Samples | Min retained (bytes) | Median retained (bytes) | Max retained (bytes) | Peak (bytes) | Cache entries |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| preview-normal | 50000 | active-prepared-preview | 1 | 991491 | 991491 | 991491 | 1986128 | — |

The active preview measurement is one prepared 50k `preview-normal` document.

## Interpretation and limitations

The current baseline separates preparation from painting: parse/read,
highlighting, view construction, first render, and every viewport operation are
distinct records. It also exposes retained Python allocations for active documents
and the diff cache. These values describe this machine and revision only; they are
not performance requirements and have no pass threshold.

`run_test` is headless, so it is not an interactive-terminal measurement. Timings
are machine-dependent. `tracemalloc` attributes Python allocations and excludes
native and process allocations, so retained-byte values are not RSS. The preview
loader retains its 1 MiB input limit. Focused dense and long cases are deliberately
not run at every size.

## Future comparisons

Generate a fresh local raw report with the same root command. Compare only runs
with the same workload IDs and dimensions, fixed 120x40 terminal size, and the
environment fields recorded above (Python, platform, CPU/count, memory, dependency
versions, source revision, and dirty state). Compare matching raw phase/operation
records and their samples/min/median/max, not only `complete-sequence`. Keep each
new raw JSON under ignored `.artifacts/`; update a checked-in reviewed baseline
only when documenting a specific revision.
