from pathlib import Path

import pytest
from rich.style import Style
from rich.text import Text

from gitpane.app import (
    format_file_label,
    highlight_new_lines,
    is_prefix_offset,
    lexer_for_entry,
    load_diff_rows,
    reconstruct_new_source,
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


def test_reconstruct_new_source_keeps_only_new_side_text_and_whitespace() -> None:
    rows = [
        Row(1, 1, "  context\t", "context"),
        Row(2, None, "removed", "remove"),
        Row(3, 2, "", "context"),
        Row(None, 3, "[added]  ", "add"),
    ]

    assert reconstruct_new_source(rows) == "  context\t\n\n[added]  "


@pytest.mark.parametrize(
    "rows",
    [[], [Row(1, None, "removed", "remove"), Row(2, None, "also removed", "remove")]],
)
def test_reconstruct_new_source_returns_empty_for_no_new_side(rows: list[Row]) -> None:
    assert reconstruct_new_source(rows) == ""


def test_lexer_for_entry_forwards_exact_path_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_guess_lexer(path: str, source: str) -> str:
        calls.append((path, source))
        return "returned unchanged"

    monkeypatch.setattr("gitpane.app.Syntax.guess_lexer", fake_guess_lexer)
    entry = FileEntry("directory with spaces/example.PY", Side.STAGED, "M")
    source = "print('source')\n"

    assert lexer_for_entry(entry, source) == "returned unchanged"
    assert calls == [("directory with spaces/example.PY", source)]


def test_highlight_new_lines_uses_one_whole_source_pass_and_retains_blank_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    highlighted = Text("first\n\nthird")
    highlighted.stylize("bold", 0, 5)
    highlighted.stylize("italic", 7, 12)

    class FakeSyntax:
        def __init__(self, source: str, lexer: str) -> None:
            calls.append(("init", source, lexer))

        @staticmethod
        def guess_lexer(path: str, source: str) -> str:
            calls.append(("guess", path, source))
            return "fake-lexer"

        def highlight(self, source: str) -> Text:
            calls.append(("highlight", source))
            return highlighted

    monkeypatch.setattr("gitpane.app.Syntax", FakeSyntax)
    entry = FileEntry("src/example.py", Side.UNSTAGED, "M")
    rows = [
        Row(1, 1, "first", "context"),
        Row(2, None, "removed", "remove"),
        Row(None, 2, "", "add"),
        Row(3, 3, "third", "context"),
    ]

    lines = highlight_new_lines(entry, rows)

    assert calls == [
        ("guess", "src/example.py", "first\n\nthird"),
        ("init", "first\n\nthird", "fake-lexer"),
        ("highlight", "first\n\nthird"),
    ]
    assert all(isinstance(line, Text) for line in lines)
    assert [line.plain for line in lines] == ["first", "", "third"]
    assert [(span.start, span.end, span.style) for span in lines[0].spans] == [
        (0, 5, "bold")
    ]
    assert [(span.start, span.end, span.style) for span in lines[2].spans] == [
        (0, 5, "italic")
    ]


def test_highlight_new_lines_skips_lexer_and_highlighter_for_all_removals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*_: object) -> None:
        raise AssertionError("highlighting should not run")

    monkeypatch.setattr("gitpane.app.Syntax", unexpected)
    entry = FileEntry("removed.py", Side.STAGED, "M")

    assert highlight_new_lines(entry, [Row(1, None, "removed", "remove")]) == []


def test_render_diff_rows_uses_plain_columns_and_complete_change_row_styles() -> None:
    entry = FileEntry("example.txt", Side.STAGED, "M")
    rendered = render_diff_rows(
        entry,
        [
            Row(1, 1, "context [not markup]", "context"),
            Row(2, None, "removed", "remove"),
            Row(None, 2, "added", "add"),
        ],
    )

    assert (
        rendered.plain
        == "     1    1 context [not markup]\n-    2      removed\n+         2 added"
    )
    assert [
        (span.start, span.end, span.style)
        for span in rendered.spans
        if span.style in {Style(bgcolor="#351b20"), Style(bgcolor="#142b1d")}
    ] == [
        (33, 52, Style(bgcolor="#351b20")),
        (53, 70, Style(bgcolor="#142b1d")),
    ]


def test_render_diff_rows_preserves_empty_rows_without_extra_newlines() -> None:
    rendered = render_diff_rows(
        FileEntry("empty.txt", Side.STAGED, "M"), [Row(None, None, "", "context")]
    )

    assert rendered.plain == "            "
    assert rendered.spans == []


def test_render_diff_rows_projects_highlights_by_new_side_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = FileEntry("src/example.py", Side.UNSTAGED, "M")
    rows = [
        Row(20, 10, "context", "context"),
        Row(21, None, "removed", "remove"),
        Row(None, 30, "added", "add"),
    ]
    context = Text("context", style=Style(color="cyan"))
    addition = Text("added", style=Style(color="magenta"))
    calls: list[tuple[FileEntry, list[Row]]] = []

    def fake_highlight_new_lines(
        received_entry: FileEntry, received_rows: list[Row]
    ) -> list[Text]:
        calls.append((received_entry, received_rows))
        return [context, addition]

    monkeypatch.setattr("gitpane.app.highlight_new_lines", fake_highlight_new_lines)

    rendered = render_diff_rows(entry, rows)

    assert calls == [(entry, rows)]
    assert (
        rendered.plain == "    20   10 context\n-   21      removed\n+        30 added"
    )
    spans = [(span.start, span.end, span.style) for span in rendered.spans]
    assert (12, 19, Style(color="cyan")) in spans
    assert (52, 57, Style(color="magenta")) in spans
    background_spans = [
        (start, end, style)
        for start, end, style in spans
        if style in {Style(bgcolor="#351b20"), Style(bgcolor="#142b1d")}
    ]
    assert background_spans == [
        (20, 39, Style(bgcolor="#351b20")),
        (40, 57, Style(bgcolor="#142b1d")),
    ]
    assert all(
        isinstance(style, Style) and style.color is None
        for _, _, style in background_spans
    )
    syntax_spans = [
        (start, end, style)
        for start, end, style in spans
        if style in {Style(color="cyan"), Style(color="magenta")}
    ]
    assert syntax_spans == [
        (12, 19, Style(color="cyan")),
        (52, 57, Style(color="magenta")),
    ]
    assert all(
        start >= 12 and end <= 19 or start >= 52 and end <= 57
        for start, end, style in spans
        if style in {Style(color="cyan"), Style(color="magenta")}
    )
    assert not any(
        start < 39 and end > 20 and isinstance(style, Style) and style.color is not None
        for start, end, style in spans
    )
    assert not any(
        start < 19
        and end > 0
        and isinstance(style, Style)
        and style.bgcolor is not None
        for start, end, style in spans
    )


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
