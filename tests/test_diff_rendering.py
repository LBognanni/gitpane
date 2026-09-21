from pathlib import Path

import pytest
from rich.style import Style
from rich.text import Text

from gitpane.app import (
    DiffView,
    build_diff_view,
    highlight_new_lines,
    lexer_for_entry,
    load_diff_view,
    reconstruct_new_source,
    render_diff_rows,
)
from gitpane.diff import Row
from gitpane.model import FileEntry, Side


def join_diff_lines(lines: tuple[Text, ...]) -> Text:
    """Join prepared lines for assertions about their text and spans."""
    result = Text()
    for index, line in enumerate(lines):
        if index:
            result.append("\n")
        result.append_text(line)
    return result


@pytest.fixture(autouse=True)
def _clear_diff_view_cache() -> None:
    build_diff_view.cache_clear()


def test_load_diff_view_forwards_root_and_entry_to_git_diff_then_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path("/repo")
    entry = FileEntry("file.txt", Side.STAGED, "M")
    patch = "raw patch"
    view = DiffView((Text("built"),), ())
    calls: list[tuple[object, ...]] = []

    def fake_diff(received_root: Path, received_entry: FileEntry) -> str:
        calls.append(("diff", received_root, received_entry))
        return patch

    def fake_build_diff_view(
        received_entry: FileEntry, received_patch: str
    ) -> DiffView:
        calls.append(("build", received_entry, received_patch))
        return view

    monkeypatch.setattr("gitpane.app.git.diff", fake_diff)
    monkeypatch.setattr("gitpane.app.build_diff_view", fake_build_diff_view)

    assert load_diff_view(root, entry) is view
    assert calls == [("diff", root, entry), ("build", entry, patch)]


def test_build_diff_view_prepares_independent_lines_without_a_joined_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = FileEntry("example.txt", Side.STAGED, "M")
    rows = [
        Row(1, 1, "context [not markup]", "context"),
        Row(2, None, "removed", "remove"),
        Row(None, 2, "added", "add"),
    ]
    monkeypatch.setattr("gitpane.app.diff.parse", lambda _: rows)

    view = build_diff_view(entry, "irrelevant patch text")

    assert isinstance(view.lines, tuple)
    assert [line.plain for line in view.lines] == [
        "     1    1 context [not markup]",
        "-    2      removed",
        "+         2 added",
    ]
    assert view.lines == render_diff_rows(entry, rows)
    assert not hasattr(view, "text")


def test_build_diff_view_reports_changes_for_a_diff_with_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = FileEntry("example.diff", Side.STAGED, "M")
    rows = [
        Row(1, 1, "context", "context"),
        Row(2, None, "removed", "remove"),
        Row(None, 2, "added", "add"),
    ]
    monkeypatch.setattr("gitpane.app.diff.parse", lambda _: rows)

    view = build_diff_view(entry, "irrelevant patch text")

    assert view.changes == (1,)
    assert view.first_change == 1


def test_build_diff_view_reports_none_for_an_all_context_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = FileEntry("example.diff", Side.STAGED, "M")
    rows = [
        Row(1, 1, "context one", "context"),
        Row(2, 2, "context two", "context"),
    ]
    monkeypatch.setattr("gitpane.app.diff.parse", lambda _: rows)

    view = build_diff_view(entry, "irrelevant patch text")

    assert view.changes == ()
    assert view.first_change is None


def test_build_diff_view_caches_repeated_identical_entry_and_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    entry = FileEntry("a.txt", Side.STAGED, "M")
    patch = "patch a"

    def fake_parse(received_patch: str) -> list[Row]:
        calls.append("parse")
        return [Row(1, 1, received_patch, "context")]

    def fake_render_diff_rows(
        received_entry: FileEntry, rows: list[Row]
    ) -> tuple[Text, ...]:
        calls.append("render")
        return (Text(rows[0].text),)

    monkeypatch.setattr("gitpane.app.diff.parse", fake_parse)
    monkeypatch.setattr("gitpane.app.render_diff_rows", fake_render_diff_rows)

    first = build_diff_view(entry, patch)
    second = build_diff_view(entry, patch)

    assert calls == ["parse", "render"]
    assert first is second
    assert first.lines is second.lines


def test_build_diff_view_rebuilds_for_a_different_patch_on_the_same_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    entry = FileEntry("a.txt", Side.STAGED, "M")

    def fake_parse(received_patch: str) -> list[Row]:
        calls.append("parse")
        return [Row(1, 1, received_patch, "context")]

    def fake_render_diff_rows(
        received_entry: FileEntry, rows: list[Row]
    ) -> tuple[Text, ...]:
        calls.append("render")
        return (Text(rows[0].text),)

    monkeypatch.setattr("gitpane.app.diff.parse", fake_parse)
    monkeypatch.setattr("gitpane.app.render_diff_rows", fake_render_diff_rows)

    first = build_diff_view(entry, "patch a")
    second = build_diff_view(entry, "patch b")

    assert calls == ["parse", "render", "parse", "render"]
    assert first.lines[0].plain == "patch a"
    assert second.lines[0].plain == "patch b"


def test_build_diff_view_rebuilds_for_a_different_entry_with_the_same_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    patch = "shared patch"

    def fake_parse(received_patch: str) -> list[Row]:
        calls.append("parse")
        return [Row(1, 1, received_patch, "context")]

    def fake_render_diff_rows(
        received_entry: FileEntry, rows: list[Row]
    ) -> tuple[Text, ...]:
        calls.append("render")
        return (Text(f"{received_entry.path}:{rows[0].text}"),)

    monkeypatch.setattr("gitpane.app.diff.parse", fake_parse)
    monkeypatch.setattr("gitpane.app.render_diff_rows", fake_render_diff_rows)

    entry_a = FileEntry("a.txt", Side.STAGED, "M")
    entry_b = FileEntry("b.txt", Side.STAGED, "M")

    first = build_diff_view(entry_a, patch)
    second = build_diff_view(entry_b, patch)

    assert calls == ["parse", "render", "parse", "render"]
    assert first.lines[0].plain == "a.txt:shared patch"
    assert second.lines[0].plain == "b.txt:shared patch"


def test_build_diff_view_evicts_the_oldest_entry_after_a_fifth_distinct_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_parse(received_patch: str) -> list[Row]:
        calls.append("parse")
        return [Row(1, 1, received_patch, "context")]

    def fake_render_diff_rows(
        received_entry: FileEntry, rows: list[Row]
    ) -> tuple[Text, ...]:
        calls.append("render")
        return (Text(rows[0].text),)

    monkeypatch.setattr("gitpane.app.diff.parse", fake_parse)
    monkeypatch.setattr("gitpane.app.render_diff_rows", fake_render_diff_rows)

    entries = [FileEntry(f"{i}.txt", Side.STAGED, "M") for i in range(5)]

    for entry in entries:
        build_diff_view(entry, "patch")

    assert calls == ["parse", "render"] * 5
    calls.clear()

    build_diff_view(entries[0], "patch")
    assert calls == ["parse", "render"]


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
    lines = render_diff_rows(
        entry,
        [
            Row(1, 1, "context [not markup]", "context"),
            Row(2, None, "removed", "remove"),
            Row(None, 2, "added", "add"),
        ],
    )
    rendered = join_diff_lines(lines)

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
    assert [
        [
            (span.start, span.end, span.style)
            for span in line.spans
            if span.style in {Style(bgcolor="#351b20"), Style(bgcolor="#142b1d")}
        ]
        for line in lines
    ] == [
        [],
        [(0, 19, Style(bgcolor="#351b20"))],
        [(0, 17, Style(bgcolor="#142b1d"))],
    ]


def test_render_diff_rows_preserves_empty_rows_without_extra_newlines() -> None:
    lines = render_diff_rows(
        FileEntry("empty.txt", Side.STAGED, "M"), [Row(None, None, "", "context")]
    )

    rendered = join_diff_lines(lines)
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

    lines = render_diff_rows(entry, rows)
    rendered = join_diff_lines(lines)

    assert calls == [(entry, rows)]
    assert (
        rendered.plain == "    20   10 context\n-   21      removed\n+        30 added"
    )
    spans = [(span.start, span.end, span.style) for span in rendered.spans]
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
        start <= 19
        and end > 0
        and isinstance(style, Style)
        and style.bgcolor is not None
        for start, end, style in spans
    )
    assert [(span.start, span.end, span.style) for span in lines[0].spans] == [
        (12, 19, Style(color="cyan"))
    ]
    assert [(span.start, span.end, span.style) for span in lines[1].spans] == [
        (0, 19, Style(bgcolor="#351b20"))
    ]
    assert [(span.start, span.end, span.style) for span in lines[2].spans] == [
        (12, 17, Style(color="magenta")),
        (0, 17, Style(bgcolor="#142b1d")),
    ]
