import asyncio
from pathlib import Path

import pytest
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual.widgets import Static, TabbedContent, Tree

from gitpane.app import (
    MAX_PREVIEW_BYTES,
    DiffView,
    GitPaneApp,
    PreviewView,
    build_diff_view,
    format_commit_label,
    format_file_label,
    highlight_new_lines,
    is_current_request,
    is_prefix_offset,
    join_diff_lines,
    lexer_for_entry,
    load_diff_view,
    load_preview_view,
    reconstruct_new_source,
    render_diff_rows,
    toggle_file,
)
from gitpane.diff import Row
from gitpane.model import Commit, CommitFile, FileEntry, RepoState, Side
from gitpane.widgets import CodeScroll, CodeView, JumpScrollBar, scrollbar_click_target


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


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        (":bug: Fix crash", "\U0001f41b Fix crash abc1234"),
        ("Plain subject", "Plain subject abc1234"),
        (":not_a_gitmoji: Keep unknown", ":not_a_gitmoji: Keep unknown abc1234"),
    ],
)
def test_format_commit_label_expands_gitmoji_and_places_hash_last(
    subject: str, expected: str
) -> None:
    commit = Commit("full-hash", "abc1234", None, subject)
    label = format_commit_label(commit)

    assert label.plain == expected
    assert [(span.start, span.end, span.style) for span in label.spans] == [
        (len(expected) - 7, len(expected), "dim")
    ]


@pytest.fixture(autouse=True)
def _clear_diff_view_cache() -> None:
    build_diff_view.cache_clear()


def test_load_diff_view_forwards_root_and_entry_to_git_diff_then_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path("/repo")
    entry = FileEntry("file.txt", Side.STAGED, "M")
    patch = "raw patch"
    view = DiffView((Text("built"),), None)
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


def test_load_preview_view_builds_numbered_non_wrapping_syntax(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text("answer = 42\n")

    view = load_preview_view(path)

    assert isinstance(view, PreviewView)
    assert isinstance(view.content, Syntax)
    assert view.content.code == "answer = 42\n"
    assert view.content.line_numbers is True
    assert view.content.word_wrap is False


@pytest.mark.parametrize(
    ("name", "contents", "message"),
    [
        ("binary.dat", b"before\0after", "Binary files cannot be previewed."),
        ("invalid.txt", b"\xff", "File is not valid UTF-8."),
        (
            "large.txt",
            b"x" * (MAX_PREVIEW_BYTES + 1),
            "File is too large to preview (maximum 1 MiB).",
        ),
    ],
)
def test_load_preview_view_returns_friendly_messages(
    tmp_path: Path, name: str, contents: bytes, message: str
) -> None:
    path = tmp_path / name
    path.write_bytes(contents)

    view = load_preview_view(path)

    assert isinstance(view.content, Text)
    assert view.content.plain == message


def test_load_preview_view_handles_disappeared_file(tmp_path: Path) -> None:
    view = load_preview_view(tmp_path / "gone.txt")

    assert isinstance(view.content, Text)
    assert view.content.plain == "File is no longer available."


def test_load_preview_view_handles_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "unreadable.txt"
    path.write_text("contents")

    def deny_open(*_: object, **__: object) -> object:
        raise PermissionError

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", deny_open)
        view = load_preview_view(path)

    assert isinstance(view.content, Text)
    assert view.content.plain == "File could not be read."


def test_load_preview_view_rejects_non_regular_files(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("outside the selected path")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    view = load_preview_view(link)

    assert isinstance(view.content, Text)
    assert view.content.plain == "Only regular files can be previewed."


def test_app_builds_file_tree_from_launch_cwd_and_refreshes_both_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    cwd = root / "nested"
    cwd.mkdir(parents=True)
    calls: list[tuple[str, Path]] = []

    def fake_status(received_root: Path) -> RepoState:
        calls.append(("status", received_root))
        return RepoState(received_root, [], [])

    def fake_files(received_cwd: Path) -> list[str]:
        calls.append(("files", received_cwd))
        return ["[directory]/example.py", "[red]top.txt"]

    monkeypatch.setattr("gitpane.app.git.status", fake_status)
    monkeypatch.setattr("gitpane.app.git.files", fake_files)

    async def exercise() -> None:
        app = GitPaneApp(root, cwd)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one("#files-tree", Tree)
            assert tree.guide_depth == 3
            assert str(tree.root.label) == f" {cwd}"
            assert [str(node.label) for node in tree.root.children] == [
                " [directory]",
                "󰈙 [red]top.txt",
            ]
            directory = tree.root.children[0]
            assert directory.data == cwd / "[directory]"
            assert directory.children[0].data == cwd / "[directory]/example.py"
            assert tree.root.children[1].data == cwd / "[red]top.txt"

            directory.expand()
            await pilot.pause()
            assert str(directory.label) == " [directory]"
            directory.collapse()
            await pilot.pause()
            assert str(directory.label) == " [directory]"

            await pilot.press("r")
            await pilot.pause()

    asyncio.run(exercise())

    assert calls == [
        ("status", root),
        ("files", cwd),
        ("status", root),
        ("files", cwd),
    ]


def test_commit_selection_expands_files_and_file_selection_uses_shared_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = Commit("full-hash", "abc1234", "parent-hash", "Add history")
    entry = CommitFile("src/history.py", "M", commit.hash, commit.parent)
    requested: list[tuple[CommitFile, int]] = []

    monkeypatch.setattr(
        "gitpane.app.git.status",
        lambda root: RepoState(
            root, [FileEntry("working.txt", Side.STAGED, "M")], [], "main"
        ),
    )
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [commit])
    monkeypatch.setattr("gitpane.app.git.commit_files", lambda _root, _commit: [entry])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    monkeypatch.setattr(
        GitPaneApp,
        "load_diff",
        lambda _self, selected, token: requested.append((selected, token)),
    )

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            tree = app.query_one("#commit-tree", Tree)
            commit_node = tree.root.children[0]
            assert str(commit_node.label) == "Add history abc1234"
            assert (
                str(app.query_one("#branch-status", Static).content) == "Branch: main"
            )

            assert await pilot.click(tree, offset=(1, 1))
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert commit_node.is_expanded
            assert len(commit_node.children) == 1
            file_node = commit_node.children[0]
            assert str(file_node.label) == "M src/history.py"

            assert await pilot.click(tree, offset=(8, 1))
            await pilot.pause()
            assert commit_node.is_collapsed

            assert await pilot.click(tree, offset=(8, 1))
            await pilot.pause()
            assert commit_node.is_expanded

            assert await pilot.click(tree, offset=(1, 1))
            await pilot.pause()
            assert commit_node.is_collapsed

            commit_node.expand()
            await pilot.pause()

            tree.select_node(file_node)
            await pilot.pause()

            assert requested == [(entry, app.request_id)]
            assert app.selection == entry
            assert str(app.query_one("#diff-title", Static).content) == entry.path

    asyncio.run(exercise())


def test_file_selection_shows_repository_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "nested" / "example.py"
    path.parent.mkdir()
    path.write_text("answer = 42\n")
    monkeypatch.setattr(
        "gitpane.app.git.status", lambda root: RepoState(root, [], [], "main")
    )
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: ["nested/example.py"])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            tree = app.query_one("#files-tree", Tree)
            tree.select_node(tree.root.children[0].children[0])
            await app.workers.wait_for_complete()
            await pilot.pause()

            title = app.query_one("#preview-title", Static)
            assert str(title.content) == "nested/example.py"

    asyncio.run(exercise())


def test_wrap_toggle_applies_independently_to_each_viewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("w")
            await pilot.pause()

            assert app.diff_wrapped is True
            assert app.preview_wrapped is False
            assert app.query_one("#diff").has_class("wrapped")
            assert app.query_one("#diff-scroll").has_class("wrapped")

            app.query_one("#main-tabs", TabbedContent).active = "files-tab"
            syntax = Syntax("value = 'a long line'", "python", word_wrap=False)
            app.apply_preview_view(PreviewView(syntax), app.preview_request_id)
            await pilot.press("w")
            await pilot.pause()

            assert app.diff_wrapped is True
            assert app.preview_wrapped is True
            assert app.query_one("#preview").has_class("wrapped")
            assert app.query_one("#preview-scroll").has_class("wrapped")
            assert syntax.word_wrap is True

            await pilot.press("w")
            await pilot.pause()

            assert app.preview_wrapped is False
            assert syntax.word_wrap is False

    asyncio.run(exercise())


def test_diff_uses_virtual_view_and_only_populates_static_when_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            virtual = app.query_one("#diff-view", CodeView)
            fallback = app.query_one("#diff", Static)
            assert str(fallback.content) == ""

            lines: tuple[Text, ...] = tuple(
                Text(f"line {index}") for index in range(40)
            )
            scroll_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
            original_scroll_to = virtual.scroll_to

            def scroll_to(*args: object, **kwargs: object) -> None:
                scroll_calls.append((args, kwargs))
                original_scroll_to(*args, **kwargs)  # type: ignore[arg-type]

            monkeypatch.setattr(virtual, "scroll_to", scroll_to)
            app.apply_diff_view(DiffView(lines, 0), app.request_id)
            await pilot.pause()

            assert virtual.lines == lines
            assert virtual.scroll_offset == (0, 0)
            assert scroll_calls == [
                ((0, 0), {"animate": False}),
                ((0, 0), {"animate": False}),
                ((0, 0), {"animate": False}),
            ]
            assert str(fallback.content) == ""

            await pilot.press("w")
            await pilot.pause()
            content = fallback.content
            assert isinstance(content, Text)
            assert content.plain == "\n".join(f"line {index}" for index in range(40))

            app.apply_diff_view(DiffView((Text("replacement"),), 0), app.request_id)
            content = fallback.content
            assert isinstance(content, Text)
            assert content.plain == "replacement"

            await pilot.press("w")
            await pilot.pause()
            assert virtual.lines == (Text("replacement"),)
            assert str(fallback.content) == ""

    asyncio.run(exercise())


def test_diff_first_change_scrolls_past_leading_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            view = app.query_one("#diff-view", CodeView)
            lines = tuple(Text(f"line {index}") for index in range(80))

            app.apply_diff_view(DiffView(lines, 17), app.request_id)
            await pilot.pause()

            assert view.scroll_offset == (0, 17)

    asyncio.run(exercise())


def test_diff_view_supports_line_page_jump_and_long_horizontal_navigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            view = app.query_one("#diff-view", CodeView)
            lines = tuple(Text(f"{row:03} " + "x" * 200) for row in range(100))
            app.apply_diff_view(DiffView(lines, None), app.request_id)
            await pilot.pause()
            view.focus()

            await pilot.press("down")
            await pilot.pause()
            assert view.scroll_y == 1

            page_height = view.scrollable_content_region.height
            await pilot.press("pagedown")
            await pilot.pause()
            assert view.scroll_y == 1 + page_height

            scrollbar = view.vertical_scrollbar
            assert await pilot.click(scrollbar, offset=(0, scrollbar.size.height - 1))
            await pilot.pause()
            assert view.scroll_y == view.max_scroll_y

            await pilot.press(*("right",) * 300)
            await pilot.pause()
            assert view.scroll_x == view.max_scroll_x

    asyncio.run(exercise())


def test_diff_request_and_refresh_clear_both_renderers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = FileEntry("example.py", Side.UNSTAGED, "M")
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    monkeypatch.setattr(GitPaneApp, "load_diff", lambda *_: None)

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            view = app.query_one("#diff-view", CodeView)
            scroll = app.query_one("#diff-scroll", CodeScroll)
            content = app.query_one("#diff", Static)
            lines = tuple(Text(f"{row:03} " + "x" * 120) for row in range(80))

            assert view.display is True
            assert scroll.display is False
            app.request_diff(entry)
            assert view.loading is True
            assert scroll.loading is False

            app.apply_diff_view(DiffView(lines, 17), app.request_id)
            await pilot.pause()
            assert app.diff_view == DiffView(lines, 17)
            assert view.lines == lines
            assert view.scroll_offset == (0, 17)
            assert str(content.content) == ""
            assert view.loading is False
            assert scroll.loading is False

            await pilot.press("w")
            await pilot.pause()
            assert view.display is False
            assert scroll.display is True
            assert content.content == join_diff_lines(lines)
            scroll.scroll_to(0, 20, animate=False)
            app.request_diff(entry)
            assert view.loading is False
            assert scroll.loading is True

            await pilot.press("r")
            await pilot.pause()
            assert app.diff_view is None
            assert view.lines == ()
            assert str(content.content) == ""
            assert view.scroll_offset == (0, 0)
            assert scroll.scroll_offset == (0, 0)
            assert view.loading is False
            assert scroll.loading is False

            await pilot.press("w")
            await pilot.pause()
            assert view.display is True
            assert scroll.display is False

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("lines", "first_change"),
    [
        ((), None),
        (tuple(Text(f"context {index}") for index in range(80)), None),
    ],
)
def test_empty_and_context_only_diffs_stay_at_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lines: tuple[Text, ...],
    first_change: int | None,
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            view = app.query_one("#diff-view", CodeView)
            view.set_document(tuple(Text("x" * 120) for _ in range(80)))
            view.scroll_to(20, 20, animate=False)
            await pilot.pause()

            app.apply_diff_view(DiffView(lines, first_change), app.request_id)
            await pilot.pause()

            assert view.scroll_offset == (0, 0)

    asyncio.run(exercise())


def test_replacing_a_scrolled_diff_resets_offsets_and_scrolls_to_first_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            view = app.query_one("#diff-view", CodeView)
            app.apply_diff_view(
                DiffView(tuple(Text("old " + "x" * 120) for _ in range(80)), 0),
                app.request_id,
            )
            await pilot.pause()
            view.scroll_to(20, 30, animate=False)
            await pilot.pause()

            replacement = tuple(Text(f"new {index}") for index in range(80))
            generation = view.document_generation
            app.apply_diff_view(DiffView(replacement, 9), app.request_id)
            await pilot.pause()

            assert view.lines == replacement
            assert view.document_generation == generation + 1
            assert view.scroll_offset == (0, 9)

    asyncio.run(exercise())


def test_diff_wrap_transitions_preserve_progress_and_reset_horizontal_scroll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            view = app.query_one("#diff-view", CodeView)
            fallback = app.query_one("#diff-scroll", CodeScroll)
            lines = tuple(Text(f"{index:03} " + "x" * 120) for index in range(100))
            app.apply_diff_view(DiffView(lines, None), app.request_id)
            await pilot.pause()
            view.scroll_to(20, 30, animate=False)
            await pilot.pause()
            unwrapped_progress = view.scroll_y / view.max_scroll_y

            await pilot.press("w")
            await pilot.pause()

            assert fallback.scroll_x == 0
            assert fallback.scroll_y / fallback.max_scroll_y == pytest.approx(
                unwrapped_progress, abs=1 / fallback.max_scroll_y
            )

            fallback.scroll_to(0, fallback.max_scroll_y / 2, animate=False)
            await pilot.pause()
            wrapped_progress = fallback.scroll_y / fallback.max_scroll_y

            await pilot.press("w")
            await pilot.pause()

            assert view.scroll_x == 0
            assert view.scroll_y / view.max_scroll_y == pytest.approx(
                wrapped_progress, abs=1 / view.max_scroll_y
            )

    asyncio.run(exercise())


def test_loading_a_new_diff_while_wrapped_updates_only_the_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            await pilot.press("w")
            await pilot.pause()
            fallback = app.query_one("#diff-scroll", CodeScroll)
            virtual = app.query_one("#diff-view", CodeView)
            fallback.loading = True
            lines = tuple(Text(f"new {index}") for index in range(40))
            scroll_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
            original_scroll_to = fallback.scroll_to

            def scroll_to(*args: object, **kwargs: object) -> None:
                scroll_calls.append((args, kwargs))
                original_scroll_to(*args, **kwargs)  # type: ignore[arg-type]

            monkeypatch.setattr(fallback, "scroll_to", scroll_to)

            app.apply_diff_view(DiffView(lines, 17), app.request_id)
            await pilot.pause()

            content = app.query_one("#diff", Static).content
            assert isinstance(content, Text)
            assert content.plain == "\n".join(f"new {index}" for index in range(40))
            assert scroll_calls == [
                ((0, 0), {"animate": False}),
                ((0, 17), {"animate": False}),
            ]
            assert fallback.loading is False
            assert virtual.lines == ()

    asyncio.run(exercise())


def test_stale_diff_application_preserves_newer_virtual_document_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            app.request_id += 1
            current = app.request_id
            newer = DiffView(
                tuple(Text(f"new {index} " + "x" * 120) for index in range(100)), 20
            )
            app.apply_diff_view(newer, current)
            await pilot.pause()
            virtual = app.query_one("#diff-view", CodeView)
            virtual.scroll_to(20, 30, animate=False)
            await pilot.pause()
            await pilot.press("w")
            await pilot.pause()
            fallback = app.query_one("#diff-scroll", CodeScroll)
            fallback.scroll_to(0, 10, animate=False)
            fallback.loading = True
            state = (
                app.diff_view,
                virtual.lines,
                virtual.document_generation,
                virtual.scroll_offset,
                app.query_one("#diff", Static).content,
                fallback.scroll_offset,
            )

            app.apply_diff_view(DiffView((Text("old"),), 0), current - 1)

            assert (
                app.diff_view,
                virtual.lines,
                virtual.document_generation,
                virtual.scroll_offset,
                app.query_one("#diff", Static).content,
                fallback.scroll_offset,
            ) == state
            assert fallback.loading is True

    asyncio.run(exercise())


def test_loaded_preview_uses_current_wrap_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            app.query_one("#main-tabs", TabbedContent).active = "files-tab"
            await pilot.press("w")
            await pilot.pause()

            syntax = Syntax("value = 1", "python", word_wrap=False)
            app.apply_preview_view(PreviewView(syntax), app.preview_request_id)

            assert syntax.word_wrap is True

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("y", "expected"),
    [
        (0, 0),
        (10, 475),
        (19, 900),
    ],
)
def test_scrollbar_click_target_centers_and_clamps(y: float, expected: float) -> None:
    assert scrollbar_click_target(y, 20, 1000, 100) == expected


def test_code_viewers_use_jump_scrollbar_and_unanimated_paging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test():
            scroll = app.query_one("#preview-scroll", CodeScroll)
            calls: list[tuple[str, bool]] = []
            monkeypatch.setattr(
                scroll,
                "scroll_page_up",
                lambda *, animate: calls.append(("up", animate)),
            )
            monkeypatch.setattr(
                scroll,
                "scroll_page_down",
                lambda *, animate: calls.append(("down", animate)),
            )

            scroll.action_page_up()
            scroll.action_page_down()

            assert calls == [("up", False), ("down", False)]
            assert isinstance(scroll.vertical_scrollbar, JumpScrollBar)
            assert isinstance(app.query_one("#diff-scroll"), CodeScroll)

    asyncio.run(exercise())


def test_file_preview_scrollbar_track_click_jumps_to_clicked_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            app.query_one("#main-tabs", TabbedContent).active = "files-tab"
            app.query_one("#preview", Static).update(
                Text("\n".join(map(str, range(1000))))
            )
            await pilot.pause()

            scroll = app.query_one("#preview-scroll", CodeScroll)
            scrollbar = scroll.vertical_scrollbar
            click_y = scrollbar.size.height * 3 // 4
            expected = scrollbar_click_target(
                click_y,
                scrollbar.size.height,
                scrollbar.window_virtual_size,
                scrollbar.window_size,
            )

            assert await pilot.click(scrollbar, offset=(0, click_y))
            await pilot.pause()

            assert scroll.scroll_y == pytest.approx(expected)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("token", "current", "expected"),
    [
        (3, 3, True),
        (2, 3, False),
        (4, 3, False),
    ],
)
def test_is_current_request_matches_only_the_current_token(
    token: int, current: int, expected: bool
) -> None:
    assert is_current_request(token, current) is expected


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


def test_build_diff_view_reports_first_change_for_a_diff_with_changes(
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
