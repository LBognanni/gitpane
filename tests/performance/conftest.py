"""Pytest fixtures shared by performance workloads."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.performance.reporting import PerformanceReport, environment_metadata


@pytest.fixture(scope="session")
def performance_report(pytestconfig: pytest.Config) -> Iterator[PerformanceReport]:
    """Write the report even though performance values have no pass/fail limit."""
    root = Path(str(pytestconfig.rootpath))
    report = PerformanceReport(environment_metadata(root))
    yield report
    report.write(root / ".artifacts" / "performance-baseline.json")
