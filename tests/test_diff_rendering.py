from pathlib import Path

import pytest
from rich.style import Style
from rich.text import Text

import gitpane.app
from gitpane.app import (
    build_diff_view,
    highlight_new_lines,
    load_diff_view,
    reconstruct_new_source,
    render_diff_rows,
)
from gitpane.diff import Row
from gitpane.model import FileEntry, Side

GUTTER_WIDTH = 12

PATCH = """\
diff --git a/module.py b/module.py
index 1111111..2222222 100644
--- a/module.py
+++ b/module.py
@@ -1,3 +1,4 @@
 import os
-x = 1
+x = 2
+
 def f():
"""


def hunk(body: str) -> str:
    """Wrap hunk lines in file headers so they parse as a unified patch."""
    lines = body.splitlines()
    old = sum(not line.startswith("+") for line in lines)
    new = sum(not line.startswith("-") for line in lines)
    return f"--- a/f\n+++ b/f\n@@ -1,{old} +1,{new} @@\n{body}"


def source_colors(line: Text) -> set[object]:
    """Return the distinct foreground colors used across the source column."""
    return {style_at(line, i).color for i in range(GUTTER_WIDTH, len(line.plain))}


def style_at(line: Text, offset: int) -> Style:
    """Return the effective style of one character in a prepared line."""
    return Style.combine(
        [Style()]
        + [
            span.style
            for span in line.spans
            if span.start <= offset < span.end and isinstance(span.style, Style)
        ]
    )


@pytest.fixture(autouse=True)
def _clear_diff_view_cache() -> None:
    build_diff_view.cache_clear()


def test_load_diff_view_prepares_visible_rows_and_change_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path("/repo")
    entry = FileEntry("module.py", Side.STAGED, "M")
    requested: list[tuple[Path, FileEntry]] = []

    def fake_diff(received_root: Path, received_entry: FileEntry) -> str:
        requested.append((received_root, received_entry))
        return PATCH

    monkeypatch.setattr("gitpane.app.git.diff", fake_diff)

    view = load_diff_view(root, entry)

    assert requested == [(root, entry)]
    assert [line.plain for line in view.lines] == [
        "     1    1 import os",
        "-    2      x = 1",
        "+         2 x = 2",
        "+         3 ",
        "     3    4 def f():",
    ]
    assert view.changes == (1,)
    assert view.first_change == 1
    context, removed, added, blank_added, _ = view.lines
    assert style_at(removed, 0).bgcolor is not None
    assert style_at(added, 0).bgcolor is not None
    assert style_at(removed, 0).bgcolor != style_at(added, 0).bgcolor
    assert style_at(blank_added, 0).bgcolor == style_at(added, 0).bgcolor
    assert style_at(context, 0).bgcolor != style_at(added, 0).bgcolor
    assert style_at(context, GUTTER_WIDTH).color is not None


def test_load_diff_view_reports_no_changes_for_an_all_context_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch = hunk(" context one\n context two\n")
    monkeypatch.setattr("gitpane.app.git.diff", lambda root, entry: patch)

    view = load_diff_view(Path("/repo"), FileEntry("notes.txt", Side.STAGED, "M"))

    assert [line.plain for line in view.lines] == [
        "     1    1 context one",
        "     2    2 context two",
    ]
    assert view.changes == ()
    assert view.first_change is None


def test_diff_rows_show_bracketed_source_literally() -> None:
    view = build_diff_view(
        FileEntry("notes.txt", Side.STAGED, "M"),
        hunk("-[old]\n+[new] [/bold]\n"),
    )

    assert [line.plain for line in view.lines] == [
        "-    1      [old]",
        "+         1 [new] [/bold]",
    ]


@pytest.fixture
def count_renders(monkeypatch: pytest.MonkeyPatch) -> list[FileEntry]:
    """Record each full render performed while building a diff view."""
    renders: list[FileEntry] = []
    real_render = gitpane.app.render_diff_rows

    def counting_render(entry: FileEntry, rows: list[Row]) -> tuple[Text, ...]:
        renders.append(entry)
        return real_render(entry, rows)

    monkeypatch.setattr("gitpane.app.render_diff_rows", counting_render)
    return renders


def test_build_diff_view_renders_an_identical_entry_and_patch_once(
    count_renders: list[FileEntry],
) -> None:
    entry = FileEntry("module.py", Side.STAGED, "M")

    first = build_diff_view(entry, PATCH)
    second = build_diff_view(entry, PATCH)

    assert len(count_renders) == 1
    assert [line.plain for line in second.lines] == [line.plain for line in first.lines]


def test_build_diff_view_shows_new_output_for_a_changed_patch(
    count_renders: list[FileEntry],
) -> None:
    entry = FileEntry("module.py", Side.STAGED, "M")

    first = build_diff_view(entry, hunk("-a = 1\n+a = 2\n"))
    second = build_diff_view(entry, hunk("-a = 1\n+a = 3\n"))

    assert first.lines[1].plain.endswith("a = 2")
    assert second.lines[1].plain.endswith("a = 3")


def test_build_diff_view_shows_new_output_for_a_changed_entry(
    count_renders: list[FileEntry],
) -> None:
    patch = hunk("-value\n+value = 1\n")

    as_python = build_diff_view(FileEntry("value.py", Side.STAGED, "M"), patch)
    as_text = build_diff_view(FileEntry("value.txt", Side.STAGED, "M"), patch)

    assert [line.plain for line in as_python.lines] == [
        line.plain for line in as_text.lines
    ]
    # Only the Python entry gets more than one syntax color.
    assert len(source_colors(as_python.lines[1])) > 1
    assert len(source_colors(as_text.lines[1])) == 1


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


@pytest.mark.parametrize(
    ("path", "source", "colored_offset"),
    [
        ("example.py", "import os", 0),
        ("example.PY", "import os", 0),
        ("src/dir with spaces/example.js", "const x = 1;", 0),
        ("example.json", '{"key": 1}', 1),
        ("example.rs", "fn main() {}", 0),
    ],
)
def test_render_diff_rows_colors_source_by_filename_language(
    path: str, source: str, colored_offset: int
) -> None:
    entry = FileEntry(path, Side.UNSTAGED, "M")

    (line,) = render_diff_rows(entry, [Row(1, 1, source, "context")])

    assert line.plain == f"     1    1 {source}"
    assert style_at(line, GUTTER_WIDTH + colored_offset).color is not None


def test_render_diff_rows_leaves_unrecognized_source_uncolored() -> None:
    entry = FileEntry("notes.unknown", Side.UNSTAGED, "M")

    (line,) = render_diff_rows(entry, [Row(1, 1, "plain words", "context")])

    assert line.plain == "     1    1 plain words"
    assert len(source_colors(line)) == 1


def test_highlight_new_lines_retains_blank_lines_in_new_side_order() -> None:
    entry = FileEntry("src/example.py", Side.UNSTAGED, "M")
    rows = [
        Row(1, 1, "import os", "context"),
        Row(2, None, "removed = 1", "remove"),
        Row(None, 2, "", "add"),
        Row(3, 3, "def f(): pass", "context"),
    ]

    lines = highlight_new_lines(entry, rows)

    assert [line.plain for line in lines] == ["import os", "", "def f(): pass"]
    assert style_at(lines[0], 0).color is not None
    assert style_at(lines[2], 0).color is not None


def test_render_diff_rows_shows_all_removals_as_removed_rows() -> None:
    entry = FileEntry("removed.py", Side.STAGED, "M")

    lines = render_diff_rows(
        entry,
        [Row(1, None, "import os", "remove"), Row(2, None, "x = 1", "remove")],
    )

    assert [line.plain for line in lines] == [
        "-    1      import os",
        "-    2      x = 1",
    ]
    for line in lines:
        assert style_at(line, 0).bgcolor is not None
        assert style_at(line, len(line.plain) - 1).bgcolor is not None
        assert style_at(line, GUTTER_WIDTH).color is None


def test_render_diff_rows_uses_plain_columns_and_full_width_change_backgrounds() -> (
    None
):
    entry = FileEntry("example.txt", Side.STAGED, "M")

    context, removed, added = render_diff_rows(
        entry,
        [
            Row(1, 1, "context [not markup]", "context"),
            Row(2, None, "removed", "remove"),
            Row(None, 2, "added", "add"),
        ],
    )

    assert context.plain == "     1    1 context [not markup]"
    assert removed.plain == "-    2      removed"
    assert added.plain == "+         2 added"
    assert style_at(context, 0).bgcolor is None
    for line in (removed, added):
        assert style_at(line, 0).bgcolor is not None
        assert style_at(line, len(line.plain) - 1).bgcolor == style_at(line, 0).bgcolor
    assert style_at(removed, 0).bgcolor != style_at(added, 0).bgcolor


def test_render_diff_rows_preserves_empty_rows() -> None:
    lines = render_diff_rows(
        FileEntry("empty.txt", Side.STAGED, "M"), [Row(None, None, "", "context")]
    )

    assert [line.plain for line in lines] == ["            "]
    assert lines[0].spans == []


def test_render_diff_rows_projects_syntax_onto_source_not_gutter() -> None:
    entry = FileEntry("src/example.py", Side.UNSTAGED, "M")
    context, removed, added = render_diff_rows(
        entry,
        [
            Row(20, 10, "import os", "context"),
            Row(21, None, "import sys", "remove"),
            Row(None, 30, "import re", "add"),
        ],
    )

    assert context.plain == "    20   10 import os"
    assert removed.plain == "-   21      import sys"
    assert added.plain == "+        30 import re"
    # The keyword is colored on the new side and the gutter never is.
    assert style_at(context, GUTTER_WIDTH).color is not None
    assert style_at(added, GUTTER_WIDTH).color is not None
    assert style_at(added, GUTTER_WIDTH).bgcolor is not None
    assert style_at(context, 0).color is None
    assert style_at(added, 0).color is None
    # Removed rows show old-side source without syntax coloring.
    assert style_at(removed, GUTTER_WIDTH).color is None
