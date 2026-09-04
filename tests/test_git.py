from pathlib import Path

from gitpane.git import _parse_status
from gitpane.model import FileEntry, Side


def test_parse_status_maps_ordinary_changes() -> None:
    root = Path("/repository")
    output = (
        "1 M. N... 100644 100644 100644 hash hash staged.txt\0"
        "1 .M N... 100644 100644 100644 hash hash unstaged.txt\0"
        "1 AD N... 100644 100644 100644 hash hash both.txt\0"
        "1 T. N... 100644 100644 100644 hash hash type-change.txt\0"
    )

    state = _parse_status(output, root)

    assert state.root == root
    assert state.staged == [
        FileEntry("staged.txt", Side.STAGED, "M"),
        FileEntry("both.txt", Side.STAGED, "A"),
        FileEntry("type-change.txt", Side.STAGED, "M"),
    ]
    assert state.unstaged == [
        FileEntry("unstaged.txt", Side.UNSTAGED, "M"),
        FileEntry("both.txt", Side.UNSTAGED, "D"),
    ]


def test_parse_status_handles_untracked_and_unsupported_records() -> None:
    root = Path("/repository")
    output = (
        "\0? path with spaces.txt\0"
        "2 R. N... 100644 100644 100644 hash hash score new.txt\0old.txt\0"
        "u UU N... 100644 100644 100644 100644 hash hash hash conflict.txt\0"
        "x unknown record\0"
        "1 D. N... 100644 100644 100644 hash hash deleted.txt\0\0"
    )

    state = _parse_status(output, root)

    assert state.staged == [FileEntry("deleted.txt", Side.STAGED, "D")]
    assert state.unstaged == [FileEntry("path with spaces.txt", Side.UNSTAGED, "?")]


def test_parse_status_skips_rename_continuation() -> None:
    state = _parse_status(
        "2 R. N... 100644 100644 100644 hash hash score new.txt\0? phantom.txt\0",
        Path("/repository"),
    )

    assert state.staged == []
    assert state.unstaged == []
