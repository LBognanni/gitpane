import json
from pathlib import Path

import pytest

from tests.performance.reporting import (
    SCHEMA_VERSION,
    PerformanceReport,
    environment_metadata,
    summarize_samples,
)


def test_summarize_samples_retains_integer_raw_values() -> None:
    assert summarize_samples([9, 3, 6]) == {
        "samples": [9, 3, 6],
        "min": 3,
        "median": 6,
        "max": 9,
    }


def test_summarize_samples_requires_a_value() -> None:
    with pytest.raises(ValueError, match="At least one"):
        summarize_samples([])


def test_environment_metadata_has_required_fixed_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tests.performance.reporting._git_output", lambda *_args: None)
    monkeypatch.setattr("tests.performance.reporting._total_memory_bytes", lambda: None)
    monkeypatch.setattr(
        "tests.performance.reporting._package_version", lambda _name: None
    )

    environment = environment_metadata(tmp_path)

    assert set(environment) == {
        "python_implementation",
        "python_version",
        "platform",
        "cpu_description",
        "cpu_count",
        "total_memory_bytes",
        "rich_version",
        "textual_version",
        "unidiff_version",
        "terminal_size",
        "timestamp_utc",
        "git_commit",
        "worktree_dirty",
    }
    assert environment["terminal_size"] == {"columns": 120, "lines": 40}


def test_report_serialization_has_stable_schema(tmp_path: Path) -> None:
    report = PerformanceReport({"platform": "test"})
    report.add_record(
        viewer="diff",
        workload_id="diff-mixed",
        line_count=1_000,
        phase="parse",
        operation="diff.parse",
        samples=[3, 1, 2],
        unit="nanoseconds",
    )
    path = tmp_path / "report.json"

    report.write(path)

    payload = json.loads(path.read_text())
    record = payload["records"][0]
    assert payload["schema_version"] == SCHEMA_VERSION
    assert record == {
        "line_count": 1_000,
        "max": 3,
        "median": 2,
        "min": 1,
        "operation": "diff.parse",
        "phase": "parse",
        "samples": [3, 1, 2],
        "schema_version": SCHEMA_VERSION,
        "unit": "nanoseconds",
        "viewer": "diff",
        "workload_id": "diff-mixed",
    }
    first = path.read_text()
    report.write(path)
    assert path.read_text() == first
