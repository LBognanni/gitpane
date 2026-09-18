from io import StringIO

import pytest

from gitpane.diff import Row, change_indices, first_change_index, main, parse


def test_parse_maps_context_removals_and_additions() -> None:
    patch = """\
--- a/example.txt
+++ b/example.txt
@@ -1,2 +1,2 @@
 unchanged
-old
+new
"""

    assert parse(patch) == [
        Row(1, 1, "unchanged", "context"),
        Row(2, None, "old", "remove"),
        Row(None, 2, "new", "add"),
    ]


def test_parse_preserves_leading_and_trailing_whitespace() -> None:
    patch = """\
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-  old  
+  new  
"""

    assert parse(patch) == [
        Row(1, None, "  old  ", "remove"),
        Row(None, 1, "  new  ", "add"),
    ]


def test_parse_removes_crlf_but_preserves_other_whitespace() -> None:
    patch = (
        "--- a/example.txt\r\n"
        "+++ b/example.txt\r\n"
        "@@ -1 +1 @@\r\n"
        "-  old  \r\n"
        "+  new  \r\n"
    )

    assert parse(patch) == [
        Row(1, None, "  old  ", "remove"),
        Row(None, 1, "  new  ", "add"),
    ]


def test_parse_flattens_multiple_hunks_and_files_in_order() -> None:
    patch = """\
--- a/first.txt
+++ b/first.txt
@@ -1 +1 @@
-first old
+first new
@@ -5 +5 @@
-second old
+second new
--- a/second.txt
+++ b/second.txt
@@ -2 +2 @@
-third old
+third new
"""

    assert parse(patch) == [
        Row(1, None, "first old", "remove"),
        Row(None, 1, "first new", "add"),
        Row(5, None, "second old", "remove"),
        Row(None, 5, "second new", "add"),
        Row(2, None, "third old", "remove"),
        Row(None, 2, "third new", "add"),
    ]


def test_parse_empty_patch() -> None:
    assert parse("") == []


def test_parse_preserves_final_changed_line_without_newline() -> None:
    patch = "--- a/example.txt\n+++ b/example.txt\n@@ -1 +1 @@\n-old\n+new"

    assert parse(patch) == [
        Row(1, None, "old", "remove"),
        Row(None, 1, "new", "add"),
    ]


def test_first_change_index_returns_zero_for_leading_change() -> None:
    assert first_change_index([Row(None, 1, "new", "add")]) == 0


def test_first_change_index_skips_context_before_change() -> None:
    rows = [
        Row(1, 1, "unchanged", "context"),
        Row(2, 2, "also unchanged", "context"),
        Row(3, None, "old", "remove"),
    ]

    assert first_change_index(rows) == 2


def test_first_change_index_returns_none_for_context_only_and_empty() -> None:
    assert first_change_index([Row(1, 1, "unchanged", "context")]) is None
    assert first_change_index([]) is None


def test_change_indices_reports_contiguous_changed_blocks() -> None:
    rows = [
        Row(1, 1, "leading context", "context"),
        Row(2, None, "old", "remove"),
        Row(None, 2, "new", "add"),
        Row(3, 3, "middle context", "context"),
        Row(None, 4, "inserted", "add"),
        Row(4, 5, "trailing context", "context"),
    ]

    assert change_indices(rows) == (1, 4)


def test_change_indices_returns_empty_for_context_only_and_empty() -> None:
    assert change_indices([Row(1, 1, "unchanged", "context")]) == ()
    assert change_indices([]) == ()


def test_main_prints_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch = """\
--- a/example.txt
+++ b/example.txt
@@ -1,2 +1,2 @@
 same
-old
+new
"""
    monkeypatch.setattr("sys.stdin", StringIO(patch))

    main()

    assert capsys.readouterr().out == "Rows: 3\nFirst change: 1\n"
