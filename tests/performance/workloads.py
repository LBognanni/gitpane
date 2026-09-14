"""Deterministic source and patch inputs for performance measurements."""

from dataclasses import dataclass
from typing import Literal

Viewer = Literal["preview", "diff"]
DiffKind = Literal["context", "remove", "add"]


@dataclass(frozen=True)
class Workload:
    """Immutable metadata for one generated workload."""

    id: str
    viewer: Viewer
    line_count: int
    max_source_width: int
    content_bytes: int
    expected_kind_counts: tuple[tuple[DiffKind, int], ...]


_SIZES = {
    "preview-normal": (1_000, 10_000, 50_000),
    "preview-dense": (1_000, 10_000),
    "preview-long": (1_000,),
    "diff-mixed": (1_000, 10_000, 50_000),
    "diff-dense": (1_000, 10_000),
    "diff-long": (1_000,),
}


def _line(workload_id: str, index: int) -> str:
    if workload_id.endswith("dense"):
        return f'value_{index:05d} = call("item", {index}, [{index}, {index + 1}])'
    if workload_id.endswith("long"):
        prefix = f'value_{index:05d} = "'
        return prefix + "x" * (4_096 - len(prefix) - 1) + '"'
    return f"value_{index:05d} = {index}"


def _uses_long_line(workload_id: str, index: int) -> bool:
    return workload_id == "preview-long" and index % 10 == 0


def _source_line(workload_id: str, index: int) -> str:
    if _uses_long_line(workload_id, index):
        return _line("preview-long", index)
    if workload_id == "preview-long":
        return _line("preview-normal", index)
    return _line(workload_id, index)


def _kind_counts(line_count: int) -> tuple[tuple[DiffKind, int], ...]:
    return (
        ("context", (line_count + 2) // 3),
        ("remove", (line_count + 1) // 3),
        ("add", line_count // 3),
    )


def _digit_count(value: int) -> int:
    return len(str(value))


def _index_width_sum(line_count: int, *, minimum: int = 0, step: int = 1) -> int:
    """Sum index widths for values in ``range(0, line_count, step)``."""
    total = 0
    lower = 0
    digits = 1
    while lower < line_count:
        upper = 10**digits
        stop = min(line_count, upper)
        first = ((lower + step - 1) // step) * step
        count = max(0, (stop - first + step - 1) // step)
        total += count * max(minimum, digits)
        lower = upper
        digits += 1
    return total


def _normal_source_bytes(line_count: int, step: int = 1) -> int:
    row_count = (line_count + step - 1) // step
    return (
        9 * row_count
        + _index_width_sum(line_count, minimum=5, step=step)
        + _index_width_sum(line_count, step=step)
    )


def _source_metadata(workload_id: str, line_count: int) -> tuple[int, int]:
    """Return maximum width and source bytes without generating every row."""
    last_index = line_count - 1
    if workload_id.endswith("long"):
        if workload_id == "preview-long":
            long_rows = (line_count + 9) // 10
            source_bytes = (
                _normal_source_bytes(line_count)
                - _normal_source_bytes(line_count, step=10)
                + long_rows * 4_096
            )
        else:
            source_bytes = line_count * 4_096
        return 4_096, source_bytes
    if workload_id.endswith("dense"):
        source_bytes = (
            29 * line_count
            + _index_width_sum(line_count, minimum=5)
            + 2 * _index_width_sum(line_count)
            + _index_width_sum(line_count + 1)
            - 1
        )
        last_width = (
            29
            + max(5, _digit_count(last_index))
            + 2 * _digit_count(last_index)
            + _digit_count(last_index + 1)
        )
        return last_width, source_bytes
    return (
        9 + max(5, _digit_count(last_index)) + _digit_count(last_index),
        _normal_source_bytes(line_count),
    )


def _patch_header(line_count: int) -> str:
    counts = dict(_kind_counts(line_count))
    old_count = counts["context"] + counts["remove"]
    new_count = counts["context"] + counts["add"]
    return (
        f"--- a/workload.py\n+++ b/workload.py\n@@ -1,{old_count} +1,{new_count} @@\n"
    )


def _metadata(workload_id: str, line_count: int) -> Workload:
    viewer: Viewer = "preview" if workload_id.startswith("preview-") else "diff"
    max_width, source_bytes = _source_metadata(workload_id, line_count)
    if viewer == "preview":
        content_bytes = source_bytes + line_count
        kind_counts: tuple[tuple[DiffKind, int], ...] = ()
    else:
        content_bytes = (
            len(_patch_header(line_count).encode("utf-8"))
            + source_bytes
            + 2 * line_count
        )
        kind_counts = _kind_counts(line_count)
    return Workload(
        workload_id, viewer, line_count, max_width, content_bytes, kind_counts
    )


WORKLOADS = tuple(
    _metadata(workload_id, line_count)
    for workload_id, sizes in _SIZES.items()
    for line_count in sizes
)


def workload_metadata(workload_id: str, line_count: int) -> Workload:
    """Return metadata for a supported workload shape at ``line_count`` rows."""
    if workload_id not in _SIZES:
        raise ValueError(f"Unknown workload: {workload_id}")
    if line_count <= 0:
        raise ValueError("line_count must be positive")
    return _metadata(workload_id, line_count)


def generate_preview(workload: Workload) -> str:
    """Generate UTF-8 preview source for a preview workload."""
    if workload.viewer != "preview":
        raise ValueError("Preview generation requires a preview workload")
    return (
        "\n".join(
            _source_line(workload.id, index) for index in range(workload.line_count)
        )
        + "\n"
    )


def generate_patch(workload: Workload) -> str:
    """Generate one valid unified patch for a diff workload."""
    if workload.viewer != "diff":
        raise ValueError("Patch generation requires a diff workload")
    prefixes = (" ", "-", "+")
    rows = (
        prefixes[index % 3] + _source_line(workload.id, index)
        for index in range(workload.line_count)
    )
    return _patch_header(workload.line_count) + "\n".join(rows) + "\n"
