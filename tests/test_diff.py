from gitpane.diff import Row, parse


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
