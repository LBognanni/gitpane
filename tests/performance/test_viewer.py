"""Report current whole-document Static rendering and viewport interactions."""

import asyncio
import gc
import time
from pathlib import Path

import pytest
from rich.syntax import Syntax
from textual.pilot import Pilot

from gitpane.app import DiffView, PreviewView, build_diff_view, load_preview_view
from gitpane.model import FileEntry, Side
from tests.performance.reporting import PerformanceReport
from tests.performance.viewer_harness import ViewerContent, ViewerHarness
from tests.performance.workloads import (
    WORKLOADS,
    Workload,
    generate_patch,
    generate_preview,
)

pytestmark = pytest.mark.performance

_ENTRY = FileEntry("workload.py", Side.UNSTAGED, "M")
_JUMP_FRACTIONS = (0.1, 0.5, 0.9, 0.1, 0.5)
_RENDER_WORKLOADS = tuple(
    workload
    for workload in WORKLOADS
    if (workload.id in {"preview-normal", "diff-mixed"})
    or (workload.line_count == 1_000 and workload.id.endswith(("dense", "long")))
)


def _prepare_content(workload: Workload, tmp_path: Path) -> ViewerContent:
    """Prepare production viewer content before any rendering clock starts."""
    if workload.viewer == "diff":
        diff_view = build_diff_view(_ENTRY, generate_patch(workload))
        assert isinstance(diff_view, DiffView)
        return diff_view.text

    path = tmp_path / "workload.py"
    path.write_text(generate_preview(workload), encoding="utf-8")
    preview_view = load_preview_view(path)
    assert isinstance(preview_view, PreviewView)
    assert isinstance(preview_view.content, Syntax)
    return preview_view.content


def _record(
    report: PerformanceReport, workload: Workload, operation: str, samples: list[int]
) -> None:
    report.add_record(
        viewer=workload.viewer,
        workload_id=workload.id,
        line_count=workload.line_count,
        phase="viewer",
        operation=operation,
        samples=samples,
        unit="nanoseconds",
    )


async def _measure_update(
    app: ViewerHarness, pilot: Pilot[None], content: ViewerContent
) -> int:
    static = app.content
    start = time.perf_counter_ns()
    static.update(content)
    await pilot.pause()
    return time.perf_counter_ns() - start


async def _exercise(
    workload: Workload, content: ViewerContent, report: PerformanceReport
) -> None:
    app = ViewerHarness()
    gc.collect()
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            sequence_start = time.perf_counter_ns()
            first_render = await _measure_update(app, pilot, content)
            scroll = app.scroll
            assert scroll.max_scroll_y > 10
            assert scroll.size.width == 120
            assert scroll.size.height == 40

            scroll.scroll_to(y=0, animate=False)
            await app.settle(pilot)
            line_samples: list[int] = []
            for _ in range(10):
                before = scroll.scroll_y
                start = time.perf_counter_ns()
                await app.line_down(pilot)
                line_samples.append(time.perf_counter_ns() - start)
                assert before < scroll.scroll_y <= scroll.max_scroll_y

            scroll.scroll_to(y=0, animate=False)
            await app.settle(pilot)
            page_samples: list[int] = []
            for _ in range(10):
                before = scroll.scroll_y
                start = time.perf_counter_ns()
                await app.page_down(pilot)
                page_samples.append(time.perf_counter_ns() - start)
                assert before < scroll.scroll_y <= scroll.max_scroll_y

            scroll.scroll_to(y=0, animate=False)
            await app.settle(pilot)
            jump_samples: list[int] = []
            for fraction in _JUMP_FRACTIONS:
                before = scroll.scroll_y
                start = time.perf_counter_ns()
                await app.jump_to_fraction(pilot, fraction)
                jump_samples.append(time.perf_counter_ns() - start)
                assert before != scroll.scroll_y
                assert 0 <= scroll.scroll_y <= scroll.max_scroll_y

            horizontal_samples: list[int] = []
            if scroll.max_scroll_x > 0:
                for _ in range(5):
                    assert scroll.scroll_x == 0
                    start = time.perf_counter_ns()
                    await app.horizontal_positive_and_reset(pilot)
                    horizontal_samples.append(time.perf_counter_ns() - start)
                    assert 0 < scroll.scroll_x <= scroll.max_scroll_x
                    await app.reset_horizontal(pilot)
                    assert scroll.scroll_x == 0

            resize_samples: list[int] = []
            start = time.perf_counter_ns()
            await pilot.resize_terminal(100, 30)
            await app.settle(pilot)
            resize_samples.append(time.perf_counter_ns() - start)
            assert scroll.size.width == 100
            assert scroll.size.height == 30
            start = time.perf_counter_ns()
            await pilot.resize_terminal(120, 40)
            await app.settle(pilot)
            resize_samples.append(time.perf_counter_ns() - start)
            assert scroll.size.width == 120
            assert scroll.size.height == 40

            initial_wrapped = False
            wrap_samples: list[int] = []
            sequence_end = 0
            for wrapped in (True, False):
                start = time.perf_counter_ns()
                await app.set_wrapped(pilot, wrapped)
                operation_end = time.perf_counter_ns()
                wrap_samples.append(operation_end - start)
                if not wrapped:
                    sequence_end = operation_end
                assert app.content.has_class("wrapped") is wrapped
                assert scroll.has_class("wrapped") is wrapped
                if isinstance(content, Syntax):
                    assert content.word_wrap is wrapped
            assert not app.content.has_class("wrapped")
            assert not scroll.has_class("wrapped")
            if isinstance(content, Syntax):
                assert content.word_wrap is initial_wrapped

            _record(report, workload, "first-render", [first_render])
            _record(report, workload, "line-scroll", line_samples)
            _record(report, workload, "page-scroll", page_samples)
            _record(report, workload, "jump-scroll", jump_samples)
            if horizontal_samples:
                _record(report, workload, "horizontal-scroll", horizontal_samples)
            _record(report, workload, "resize", resize_samples)
            _record(report, workload, "wrap-toggle", wrap_samples)
            _record(
                report,
                workload,
                "complete-sequence",
                [sequence_end - sequence_start],
            )
    finally:
        gc.collect()


@pytest.mark.parametrize("workload", _RENDER_WORKLOADS)
def test_static_viewer_operations(
    workload: Workload, tmp_path: Path, performance_report: PerformanceReport
) -> None:
    """Measure the required rendering matrix in a fresh 120 by 40 headless app."""
    content = _prepare_content(workload, tmp_path)
    try:
        asyncio.run(_exercise(workload, content, performance_report))
    finally:
        del content
        build_diff_view.cache_clear()
        gc.collect()
