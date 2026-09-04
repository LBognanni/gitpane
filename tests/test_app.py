from pathlib import Path

import pytest
from rich.style import Style

from gitpane.app import format_file_label, load_diff_rows, render_diff_rows
from gitpane.diff import Row
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


def test_load_diff_rows_forwards_the_raw_patch_to_the_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path("/repo")
    entry = FileEntry("file.txt", Side.STAGED, "M")
    patch = "raw patch"
    rows = [Row(1, 1, "line", "context")]
    calls: list[tuple[object, ...]] = []

    def fake_diff(received_root: Path, received_entry: FileEntry) -> str:
        calls.append(("diff", received_root, received_entry))
        return patch

    def fake_parse(received_patch: str) -> list[Row]:
        calls.append(("parse", received_patch))
        return rows

    monkeypatch.setattr("gitpane.app.git.diff", fake_diff)
    monkeypatch.setattr("gitpane.app.diff.parse", fake_parse)

    assert load_diff_rows(root, entry) is rows
    assert calls == [("diff", root, entry), ("parse", patch)]


def test_render_diff_rows_uses_plain_columns_and_complete_change_row_styles() -> None:
    rendered = render_diff_rows(
        [
            Row(1, 1, "context [not markup]", "context"),
            Row(2, None, "removed", "remove"),
            Row(None, 2, "added", "add"),
        ]
    )

    assert (
        rendered.plain
        == "     1    1 context [not markup]\n-    2      removed\n+         2 added"
    )
    assert [(span.start, span.end, span.style) for span in rendered.spans] == [
        (33, 52, Style(bgcolor="red")),
        (53, 70, Style(bgcolor="green")),
    ]


def test_render_diff_rows_preserves_empty_rows_without_extra_newlines() -> None:
    rendered = render_diff_rows([Row(None, None, "", "context")])

    assert rendered.plain == "            "
    assert rendered.spans == []
