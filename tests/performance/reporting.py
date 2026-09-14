"""Structured, machine-readable reporting for performance workloads."""

import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

SCHEMA_VERSION = 1
Viewer = Literal["diff", "preview"]


def summarize_samples(samples: list[int]) -> dict[str, int | list[int]]:
    """Return integer descriptive statistics while retaining all raw samples."""
    if not samples:
        raise ValueError("At least one sample is required")
    ordered = sorted(samples)
    return {
        "samples": samples,
        "min": ordered[0],
        "median": ordered[len(ordered) // 2],
        "max": ordered[-1],
    }


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _total_memory_bytes() -> int | None:
    """Get installed memory from portable OS interfaces when they are available."""
    if hasattr(os, "sysconf"):
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (OSError, ValueError):
            pass
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def _git_output(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def environment_metadata(root: Path) -> dict[str, object]:
    """Collect report context outside all measured workload regions."""
    commit = _git_output(root, "rev-parse", "HEAD")
    dirty_output = _git_output(root, "status", "--porcelain")
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "cpu_description": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "total_memory_bytes": _total_memory_bytes(),
        "rich_version": _package_version("rich"),
        "textual_version": _package_version("textual"),
        "unidiff_version": _package_version("unidiff"),
        "terminal_size": {"columns": 120, "lines": 40},
        "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "worktree_dirty": bool(dirty_output) if dirty_output is not None else None,
    }


class PerformanceReport:
    """Accumulate comparison records and serialize them deterministically."""

    def __init__(self, environment: dict[str, object]) -> None:
        self.environment = environment
        self.records: list[dict[str, object]] = []

    def add_record(
        self,
        *,
        viewer: Viewer,
        workload_id: str,
        line_count: int,
        phase: str,
        operation: str,
        samples: list[int],
        unit: Literal["nanoseconds", "bytes"],
        **details: object,
    ) -> dict[str, object]:
        """Add one report-only measurement record."""
        record: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "viewer": viewer,
            "workload_id": workload_id,
            "line_count": line_count,
            "phase": phase,
            "operation": operation,
            "unit": unit,
            **summarize_samples(samples),
            **details,
        }
        self.records.append(record)
        return record

    def as_dict(self) -> dict[str, object]:
        """Return the complete artifact payload."""
        return {
            "schema_version": SCHEMA_VERSION,
            "environment": self.environment,
            "records": self.records,
        }

    def write(self, path: Path) -> None:
        """Write stable, readable JSON for later baseline comparisons."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n")
