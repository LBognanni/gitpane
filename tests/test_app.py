import pytest

from gitpane.app import format_file_label
from gitpane.model import FileEntry, Side


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (
            FileEntry("path with spaces.txt", Side.STAGED, "M"),
            "[ ] M path with spaces.txt",
        ),
        (FileEntry("-leading-dash.txt", Side.UNSTAGED, "?"), "[ ] ? -leading-dash.txt"),
        (FileEntry("[brackets].txt", Side.UNSTAGED, "M"), "[ ] M [brackets].txt"),
    ],
)
def test_format_file_label_preserves_plain_paths(
    entry: FileEntry, expected: str
) -> None:
    assert format_file_label(entry) == expected
