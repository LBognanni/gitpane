import pytest

pytestmark = pytest.mark.performance


def test_performance_marker_selection_sentinel() -> None:
    """Keep an inexpensive marked test available before benchmarks are added."""
    assert True
