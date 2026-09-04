from pathlib import Path

import pytest
from rich.style import Style

from gitpane.app import (
    format_file_label,
    is_prefix_offset,
    load_diff_rows,
    render_diff_rows,
    toggle_file,
)
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


@pytest.mark.parametrize(
    ("entry", "expected_call"),
    [
        (
            FileEntry("staged path.txt", Side.STAGED, "M"),
            ("unstage", "staged path.txt"),
        ),
        (
            FileEntry("unstaged path.txt", Side.UNSTAGED, "M"),
            ("stage", "unstaged path.txt"),
        ),
        (
            FileEntry("untracked path.txt", Side.UNSTAGED, "?"),
            ("stage", "untracked path.txt"),
        ),
    ],
)
def test_toggle_file_dispatches_by_side_and_preserves_path(
    monkeypatch: pytest.MonkeyPatch,
    entry: FileEntry,
    expected_call: tuple[str, str],
) -> None:
    root = Path("/repo")
    calls: list[tuple[str, Path, str]] = []

    def fake_stage(received_root: Path, path: str) -> None:
        calls.append(("stage", received_root, path))

    def fake_unstage(received_root: Path, path: str) -> None:
        calls.append(("unstage", received_root, path))

    monkeypatch.setattr("gitpane.app.git.stage", fake_stage)
    monkeypatch.setattr("gitpane.app.git.unstage", fake_unstage)

    assert toggle_file(root, entry) is None  # type: ignore[func-returns-value]
    assert calls == [(expected_call[0], root, expected_call[1])]


@pytest.mark.parametrize(
    "entry",
    [
        FileEntry("staged.txt", Side.STAGED, "M"),
        FileEntry("unstaged.txt", Side.UNSTAGED, "M"),
    ],
)
def test_toggle_file_propagates_git_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    entry: FileEntry,
) -> None:
    sentinel = RuntimeError("stage failed")

    def fake_mutation(_: Path, __: str) -> None:
        raise sentinel

    monkeypatch.setattr("gitpane.app.git.stage", fake_mutation)
    monkeypatch.setattr("gitpane.app.git.unstage", fake_mutation)

    with pytest.raises(RuntimeError) as raised:
        toggle_file(Path("/repo"), entry)

    assert raised.value is sentinel


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(-1, False), (0, True), (2, True), (3, False)],
)
def test_is_prefix_offset_includes_only_checkbox_columns(
    offset: int, expected: bool
) -> None:
    assert is_prefix_offset(offset) is expected
