"""Report-only preparation and retained Python-allocation workloads."""

import gc
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import pytest
from rich.syntax import Syntax

from gitpane import app, diff
from gitpane.app import DiffView, PreviewView
from gitpane.model import FileEntry, Side
from tests.performance.reporting import PerformanceReport, Viewer
from tests.performance.workloads import (
    WORKLOADS,
    Workload,
    generate_patch,
    generate_preview,
)

pytestmark = pytest.mark.performance

_ENTRY = FileEntry("workload.py", Side.UNSTAGED, "M")


class CacheInfo(Protocol):
    """The lru_cache statistics retained in memory report records."""

    @property
    def hits(self) -> int: ...

    @property
    def misses(self) -> int: ...

    @property
    def maxsize(self) -> int | None: ...

    @property
    def currsize(self) -> int: ...


def _sample_count(workload: Workload) -> int:
    return 3 if workload.line_count == 1_000 else 1


def _time_samples(
    operation: Callable[[], object],
    count: int,
    *,
    setup: Callable[[], object] | None = None,
) -> list[int]:
    samples: list[int] = []
    for _ in range(count):
        if setup is not None:
            setup()
        gc.collect()
        start = time.perf_counter_ns()
        operation()
        samples.append(time.perf_counter_ns() - start)
    return samples


def _record_timing(
    report: PerformanceReport,
    workload: Workload,
    phase: str,
    operation: str,
    samples: list[int],
) -> None:
    report.add_record(
        viewer=workload.viewer,
        workload_id=workload.id,
        line_count=workload.line_count,
        phase=phase,
        operation=operation,
        samples=samples,
        unit="nanoseconds",
    )


@pytest.mark.parametrize(
    "workload", [item for item in WORKLOADS if item.viewer == "diff"]
)
def test_diff_preparation(
    workload: Workload,
    monkeypatch: pytest.MonkeyPatch,
    performance_report: PerformanceReport,
) -> None:
    """Keep parsing, lexing, rendering, and cold-cache preparation separate."""
    patch = generate_patch(workload)
    rows = diff.parse(patch)
    highlighted = app.highlight_new_lines(_ENTRY, rows)
    count = _sample_count(workload)

    parse_samples = _time_samples(lambda: diff.parse(patch), count)
    _record_timing(
        performance_report,
        workload,
        "parse",
        "diff.parse",
        parse_samples,
    )
    _record_timing(
        performance_report,
        workload,
        "highlight",
        "highlight_new_lines",
        _time_samples(lambda: app.highlight_new_lines(_ENTRY, rows), count),
    )
    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(
            app, "highlight_new_lines", lambda _entry, _rows: highlighted
        )
        _record_timing(
            performance_report,
            workload,
            "view-construction",
            "render_diff_rows",
            _time_samples(lambda: app.render_diff_rows(_ENTRY, rows), count),
        )

    _record_timing(
        performance_report,
        workload,
        "prepare-total",
        "build_diff_view",
        _time_samples(
            lambda: app.build_diff_view(_ENTRY, patch),
            count,
            setup=app.build_diff_view.cache_clear,
        ),
    )
    app.build_diff_view.cache_clear()
    expected_phases = {
        ("parse", "diff.parse"),
        ("highlight", "highlight_new_lines"),
        ("view-construction", "render_diff_rows"),
        ("prepare-total", "build_diff_view"),
    }
    records = [
        record
        for record in performance_report.records
        if record["viewer"] == workload.viewer
        and record["workload_id"] == workload.id
        and record["line_count"] == workload.line_count
    ]
    assert len(records) == len(expected_phases)
    assert {
        (record["phase"], record["operation"]) for record in records
    } == expected_phases
    assert len(rows) == workload.line_count
    assert all(sample >= 0 for sample in parse_samples)


@pytest.mark.parametrize(
    "workload", [item for item in WORKLOADS if item.viewer == "preview"]
)
def test_preview_preparation(
    workload: Workload, tmp_path: Path, performance_report: PerformanceReport
) -> None:
    """Measure the bounded file read, Rich lexing, wrapper, and full sequence."""
    path = tmp_path / "workload.py"
    path.write_text(generate_preview(workload), encoding="utf-8")
    prepared = app.load_preview_view(path)
    assert isinstance(prepared.content, Syntax)
    syntax = prepared.content
    count = _sample_count(workload)

    read_samples = _time_samples(lambda: app.load_preview_view(path), count)
    _record_timing(
        performance_report,
        workload,
        "read-prepare",
        "load_preview_view",
        read_samples,
    )
    _record_timing(
        performance_report,
        workload,
        "highlight",
        "Syntax.highlight",
        _time_samples(lambda: syntax.highlight(syntax.code), count),
    )
    _record_timing(
        performance_report,
        workload,
        "view-construction",
        "PreviewView",
        _time_samples(lambda: PreviewView(syntax), count),
    )

    def prepare_total() -> PreviewView:
        view = app.load_preview_view(path)
        assert isinstance(view.content, Syntax)
        view.content.highlight(view.content.code)
        return PreviewView(view.content)

    _record_timing(
        performance_report,
        workload,
        "prepare-total",
        "load_preview_view + Syntax.highlight + PreviewView",
        _time_samples(prepare_total, count),
    )
    expected_phases = {
        ("read-prepare", "load_preview_view"),
        ("highlight", "Syntax.highlight"),
        ("view-construction", "PreviewView"),
        ("prepare-total", "load_preview_view + Syntax.highlight + PreviewView"),
    }
    records = [
        record
        for record in performance_report.records
        if record["viewer"] == workload.viewer
        and record["workload_id"] == workload.id
        and record["line_count"] == workload.line_count
    ]
    assert len(records) == len(expected_phases)
    assert {
        (record["phase"], record["operation"]) for record in records
    } == expected_phases
    assert isinstance(prepared, PreviewView)
    assert all(sample >= 0 for sample in read_samples)


def _memory_delta(factory: Callable[[], object]) -> tuple[object, int, int]:
    gc.collect()
    tracemalloc.clear_traces()
    before, _ = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    value = factory()
    current, peak = tracemalloc.get_traced_memory()
    return value, max(0, current - before), max(0, peak - before)


def _record_memory(
    report: PerformanceReport,
    *,
    viewer: Viewer,
    workload_id: str,
    line_count: int,
    operation: str,
    delta: int,
    peak: int,
    cache_info: CacheInfo | None = None,
) -> None:
    details: dict[str, object] = {
        "allocation_label": "Python allocations (tracemalloc), not process RSS",
        "peak_bytes": peak,
    }
    if cache_info is not None:
        details["cache_info"] = {
            "hits": cache_info.hits,
            "misses": cache_info.misses,
            "maxsize": cache_info.maxsize,
            "currsize": cache_info.currsize,
        }
    report.add_record(
        viewer=viewer,
        workload_id=workload_id,
        line_count=line_count,
        phase="memory",
        operation=operation,
        samples=[delta],
        unit="bytes",
        **details,
    )


def test_retained_python_allocations(
    tmp_path: Path, performance_report: PerformanceReport
) -> None:
    """Report allocations retained by active views and the four-entry diff cache."""
    diff_workload = next(
        item
        for item in WORKLOADS
        if item.id == "diff-mixed" and item.line_count == 50_000
    )
    preview_workload = next(
        item
        for item in WORKLOADS
        if item.id == "preview-normal" and item.line_count == 50_000
    )
    patch = generate_patch(diff_workload)
    preview_path = tmp_path / "memory-workload.py"
    preview_path.write_text(generate_preview(preview_workload), encoding="utf-8")

    tracemalloc.start()
    try:
        app.build_diff_view.cache_clear()
        active_diff, delta, peak = _memory_delta(
            lambda: app.build_diff_view(_ENTRY, patch)
        )
        assert isinstance(active_diff, DiffView)
        _record_memory(
            performance_report,
            viewer="diff",
            workload_id=diff_workload.id,
            line_count=diff_workload.line_count,
            operation="active-prepared-diff",
            delta=delta,
            peak=peak,
            cache_info=app.build_diff_view.cache_info(),
        )
        del active_diff
        app.build_diff_view.cache_clear()

        active_preview, delta, peak = _memory_delta(
            lambda: app.load_preview_view(preview_path)
        )
        assert isinstance(active_preview, PreviewView)
        _record_memory(
            performance_report,
            viewer="preview",
            workload_id=preview_workload.id,
            line_count=preview_workload.line_count,
            operation="active-prepared-preview",
            delta=delta,
            peak=peak,
        )
        del active_preview

        def fill_cache() -> object:
            for index in range(4):
                entry = FileEntry(f"workload-{index}.py", Side.UNSTAGED, "M")
                distinct_patch = patch.replace("workload.py", f"workload-{index}.py")
                app.build_diff_view(entry, distinct_patch)
            return app.build_diff_view.cache_info()

        app.build_diff_view.cache_clear()
        cache_info_value, delta, peak = _memory_delta(fill_cache)
        cache_info = cast(CacheInfo, cache_info_value)
        _record_memory(
            performance_report,
            viewer="diff",
            workload_id=diff_workload.id,
            line_count=diff_workload.line_count,
            operation="four-entry-diff-cache",
            delta=delta,
            peak=peak,
            cache_info=cache_info,
        )
        assert cache_info.currsize == 4
        memory_records = [
            record
            for record in performance_report.records
            if record["phase"] == "memory"
        ]
        assert {record["operation"] for record in memory_records} == {
            "active-prepared-diff",
            "active-prepared-preview",
            "four-entry-diff-cache",
        }
        assert len(memory_records) == 3
        assert all(
            record["unit"] == "bytes"
            and "allocation_label" in record
            and "peak_bytes" in record
            for record in memory_records
        )
        for record in performance_report.records:
            samples = cast(list[int], record["samples"])
            assert record["viewer"] in {"diff", "preview"}
            assert all(sample >= 0 for sample in samples)
    finally:
        app.build_diff_view.cache_clear()
        tracemalloc.stop()
