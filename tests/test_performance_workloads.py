import ast
from collections import Counter

import pytest

from gitpane.app import MAX_PREVIEW_BYTES
from gitpane.diff import first_change_index, parse
from tests.performance.workloads import (
    WORKLOADS,
    generate_patch,
    generate_preview,
    workload_metadata,
)


def test_workload_matrix_has_required_ids_and_sizes() -> None:
    sizes_by_id: dict[str, set[int]] = {}
    for workload in WORKLOADS:
        sizes_by_id.setdefault(workload.id, set()).add(workload.line_count)

    assert sizes_by_id == {
        "preview-normal": {1_000, 10_000, 50_000},
        "preview-dense": {1_000, 10_000},
        "preview-long": {1_000},
        "diff-mixed": {1_000, 10_000, 50_000},
        "diff-dense": {1_000, 10_000},
        "diff-long": {1_000},
    }


@pytest.mark.parametrize(
    "workload_id", ["preview-normal", "preview-dense", "preview-long"]
)
def test_preview_generators_are_deterministic_and_bounded(workload_id: str) -> None:
    workload = workload_metadata(workload_id, 7)

    source = generate_preview(workload)

    assert source == generate_preview(workload)
    assert len(source.splitlines()) == workload.line_count
    assert len(source.encode("utf-8")) == workload.content_bytes
    assert max(map(len, source.splitlines())) == workload.max_source_width
    assert source.encode("utf-8").decode("utf-8") == source


def test_tiny_normal_workloads_have_concrete_shape() -> None:
    preview = generate_preview(workload_metadata("preview-normal", 3))
    rows = parse(generate_patch(workload_metadata("diff-mixed", 7)))

    assert preview == "value_00000 = 0\nvalue_00001 = 1\nvalue_00002 = 2\n"
    ast.parse(preview)
    assert max(len(line) for line in preview.splitlines()) == 15
    assert Counter(row.kind for row in rows) == {
        "context": 3,
        "remove": 2,
        "add": 2,
    }
    assert max(len(row.text) for row in rows) == 15


def test_preview_metadata_is_within_preview_limit() -> None:
    previews = [workload for workload in WORKLOADS if workload.viewer == "preview"]

    assert all(workload.content_bytes <= MAX_PREVIEW_BYTES for workload in previews)


@pytest.mark.parametrize("workload_id", ["diff-mixed", "diff-dense", "diff-long"])
def test_patch_generators_have_exact_deterministic_shape(workload_id: str) -> None:
    workload = workload_metadata(workload_id, 7)

    patch = generate_patch(workload)
    rows = parse(patch)

    assert patch == generate_patch(workload)
    assert len(rows) == workload.line_count
    assert Counter(row.kind for row in rows) == dict(workload.expected_kind_counts)
    assert first_change_index(rows) == 1
    assert max(len(row.text) for row in rows) == workload.max_source_width
    assert len(patch.encode("utf-8")) == workload.content_bytes


def test_dense_and_long_shapes_have_their_special_characteristics() -> None:
    dense = generate_preview(workload_metadata("preview-dense", 3))
    long_preview = generate_preview(workload_metadata("preview-long", 11))
    long_diff = parse(generate_patch(workload_metadata("diff-long", 3)))

    assert all('call("item",' in line for line in dense.splitlines())
    assert any(len(line) == 4_096 for line in long_preview.splitlines())
    assert any(len(line) < 4_096 for line in long_preview.splitlines())
    assert {len(row.text) for row in long_diff} == {4_096}


def test_workload_metadata_rejects_invalid_requests() -> None:
    with pytest.raises(ValueError, match="Unknown workload"):
        workload_metadata("unknown", 1)
    with pytest.raises(ValueError, match="positive"):
        workload_metadata("preview-normal", 0)
