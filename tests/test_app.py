import asyncio
import subprocess
import threading
from pathlib import Path

import pytest
from rich.text import Text
from textual import events
from textual.content import Content
from textual.geometry import Offset
from textual.selection import Selection
from textual.widgets import (
    Button,
    ListView,
    Static,
    TabbedContent,
    Tree,
)

from gitpane.app import (
    DiffView,
    DiscardScreen,
    FileItem,
    GitPaneApp,
    PreviewView,
    ShortcutScreen,
    claim_first_launch,
    discard_files,
    format_commit_label,
    format_file_label,
    is_current_request,
    is_prefix_offset,
    toggle_file,
)
from gitpane.model import Commit, CommitFile, FileEntry, RepoState, Side
from gitpane.widgets import CodeView, JumpScrollBar, scrollbar_click_target


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


def test_format_file_label_marks_checked_entries() -> None:
    entry = FileEntry("example.py", Side.UNSTAGED, "M")

    assert format_file_label(entry, checked=True) == "[x] M example.py"


def test_format_file_label_explains_unsupported_entries() -> None:
    entry = FileEntry(
        "renamed.py",
        Side.STAGED,
        "R",
        "Rename from original.py is not supported.",
    )

    assert format_file_label(entry) == (
        "[!] R renamed.py - Rename from original.py is not supported."
    )


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


def test_claim_first_launch_uses_platform_state_path_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "native-state" / "gitpane"
    calls: list[tuple[object, ...]] = []

    def fake_user_state_path(*args: object, **kwargs: object) -> Path:
        calls.append((*args, kwargs))
        return state_path

    monkeypatch.setattr("gitpane.app.user_state_path", fake_user_state_path)

    assert claim_first_launch() is True
    assert (state_path / "shortcuts-shown").is_file()
    assert claim_first_launch() is False
    assert calls == [
        ("gitpane", {"appauthor": False, "ensure_exists": True}),
        ("gitpane", {"appauthor": False, "ensure_exists": True}),
    ]


def test_claim_first_launch_accepts_an_isolated_marker_path(tmp_path: Path) -> None:
    marker = tmp_path / "state" / "welcome-shown"

    assert claim_first_launch(marker) is True
    assert marker.is_file()
    assert claim_first_launch(marker) is False


def test_claim_first_launch_shows_help_when_marker_parent_is_invalid(
    tmp_path: Path,
) -> None:
    invalid_parent = tmp_path / "not-a-directory"
    invalid_parent.write_text("contents")

    assert claim_first_launch(invalid_parent / "shortcuts-shown") is True


def test_shortcut_popup_opens_on_first_launch_and_with_h(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, show_shortcuts=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, ShortcutScreen)
            assert app.screen.focused is app.screen.query_one("#close-shortcuts")
            shortcut_content = str(
                app.screen.query_one("#shortcuts-list", Static).content
            )
            assert "Mouse controls are supported throughout." in shortcut_content
            assert "s           Stage or unstage" in shortcut_content
            dialog_width = app.screen.query_one("#shortcuts-dialog").styles.width
            assert dialog_width is not None
            assert dialog_width.value == 60

            await pilot.press("h")
            await pilot.pause()
            assert not isinstance(app.screen, ShortcutScreen)

            await pilot.press("h")
            await pilot.pause()
            assert isinstance(app.screen, ShortcutScreen)

            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ShortcutScreen)

    asyncio.run(exercise())


def test_keyboard_shortcuts_navigate_and_act_on_the_focused_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = FileEntry("first.txt", Side.STAGED, "M")
    second = FileEntry("second.txt", Side.STAGED, "M")
    unstaged = FileEntry("unstaged.txt", Side.UNSTAGED, "M")
    monkeypatch.setattr(
        "gitpane.app.git.status",
        lambda root: RepoState(root, [first, second], [unstaged]),
    )
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            actions: list[tuple[str, FileEntry]] = []
            discards: list[FileEntry] = []
            monkeypatch.setattr(
                app,
                "apply_entries",
                lambda action, entries: actions.append((action, entries[0])),
            )
            monkeypatch.setattr(
                app,
                "request_discard",
                lambda entries: discards.append(entries[0]),
            )

            staged_list = app.query_one("#staged-list", ListView)
            assert staged_list.index == 0
            await pilot.press("j")
            assert staged_list.index == 1
            await pilot.press("k")
            assert staged_list.index == 0
            await pilot.press("s")

            unstaged_list = app.query_one("#unstaged-list", ListView)
            unstaged_list.index = 0
            unstaged_list.focus()
            await pilot.press("s")
            await pilot.press("d")

            assert actions == [("unstage", first), ("stage", unstaged)]
            assert discards == [unstaged]

            tabs = app.query_one("#main-tabs", TabbedContent)
            await pilot.press("2")
            assert tabs.active == "files-tab"
            assert app.focused is app.query_one("#files-tree", Tree)
            await pilot.press("1")
            assert tabs.active == "changes-tab"
            assert app.focused is not None
            assert app.focused.id == "staged-list"
            await pilot.press("j")
            assert staged_list.index == 1

            app.apply_diff_view(
                DiffView(tuple(Text(str(index)) for index in range(40)), (5, 20)),
                app.request_id,
            )
            await pilot.pause()
            await pilot.press("n")
            assert app.diff_change_index == 1
            await pilot.press("p")
            assert app.diff_change_index == 0

    asyncio.run(exercise())


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
        return ["[red]top.txt", "[directory]/example.py"]

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
    entry = CommitFile("[bold]report.txt", "M", commit.hash, commit.parent)
    requested: list[tuple[CommitFile, int]] = []

    monkeypatch.setattr(
        "gitpane.app.git.status",
        lambda root: RepoState(
            root, [FileEntry("working.txt", Side.STAGED, "M")], [], "[bold]feature"
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
            await app.workers.wait_for_complete()
            await pilot.pause()
            tree = app.query_one("#commit-tree", Tree)
            commit_node = tree.root.children[0]
            assert str(commit_node.label) == "Add history abc1234"
            branch_status = app.query_one("#branch-status", Static).render()
            assert isinstance(branch_status, Content)
            assert branch_status.plain == "Branch: [bold]feature"
            assert branch_status.spans == []

            assert await pilot.click(tree, offset=(1, 1))
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert commit_node.is_expanded
            assert len(commit_node.children) == 1
            file_node = commit_node.children[0]
            assert str(file_node.label) == "M [bold]report.txt"

            assert await pilot.click(tree, offset=(8, 1))
            assert commit_node.is_collapsed

            assert await pilot.click(tree, offset=(8, 1))
            assert commit_node.is_expanded

            assert await pilot.click(tree, offset=(1, 1))
            assert commit_node.is_collapsed

            commit_node.expand()
            await pilot.pause()

            tree.select_node(file_node)
            await pilot.pause()

            assert requested == [(entry, app.request_id)]
            assert app.selection == entry
            diff_title = app.query_one("#diff-title", Static).render()
            assert isinstance(diff_title, Content)
            assert diff_title.plain == entry.path
            assert diff_title.spans == []

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

            assert app.diff_wrapped is True
            assert app.preview_wrapped is False
            assert app.query_one("#diff-view", CodeView).wrapped is True

            app.query_one("#main-tabs", TabbedContent).active = "files-tab"
            app.apply_preview_view(
                PreviewView((Text(" 1 value = 'a long line'"),)),
                app.preview_request_id,
            )
            await pilot.press("w")

            assert app.diff_wrapped is True
            assert app.preview_wrapped is True
            assert app.query_one("#preview-view", CodeView).wrapped is True

            await pilot.press("w")

            assert app.preview_wrapped is False
            assert app.query_one("#preview-view", CodeView).wrapped is False

    asyncio.run(exercise())


def test_completed_text_selection_is_copied_to_clipboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        copied: list[str] = []
        monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
        async with app.run_test():
            view = app.query_one("#diff-view", CodeView)
            view.set_document((Text("selected text"),))
            app.screen.selections = {view: Selection(Offset(0, 0), Offset(8, 0))}

            app.on_text_selected(events.TextSelected())

            assert copied == ["selected"]

    asyncio.run(exercise())


def test_app_uses_two_virtual_code_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            viewers = list(app.query(CodeView))
            assert [viewer.id for viewer in viewers] == ["diff-view", "preview-view"]
            diff_view = app.query_one("#diff-view", CodeView)

            lines: tuple[Text, ...] = tuple(
                Text(f"line {index}") for index in range(40)
            )
            app.apply_diff_view(DiffView(lines, (0,)), app.request_id)
            await pilot.pause()

            assert diff_view.lines == lines
            assert diff_view.scroll_offset == (0, 0)

            await pilot.press("w")
            await pilot.pause()
            assert diff_view.wrapped is True

            app.apply_diff_view(DiffView((Text("replacement"),), (0,)), app.request_id)
            assert diff_view.lines == (Text("replacement"),)

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

            app.apply_diff_view(DiffView(lines, (17,)), app.request_id)
            await pilot.pause()

            assert view.scroll_offset == (0, 13)

    asyncio.run(exercise())


def test_diff_change_buttons_navigate_and_disable_at_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            lines = tuple(Text(f"line {index} " + "x" * 100) for index in range(100))
            app.apply_diff_view(DiffView(lines, (10, 30, 70)), app.request_id)
            await pilot.pause()
            previous = app.query_one("#previous-change", Button)
            next_change = app.query_one("#next-change", Button)
            view = app.query_one("#diff-view", CodeView)

            assert view.scroll_y == 6
            assert previous.disabled is True
            assert next_change.disabled is False

            assert await pilot.click(next_change)
            await pilot.pause()
            assert view.scroll_y == 26
            assert previous.disabled is False
            assert next_change.disabled is False

            next_change.press()
            await pilot.pause()
            assert view.scroll_y == 66
            assert previous.disabled is False
            assert next_change.disabled is True

            assert await pilot.click(previous)
            await pilot.pause()
            assert view.scroll_y == 26

            await pilot.press("w")
            await pilot.pause()
            previous.press()
            await pilot.pause()
            wrapped_row = view.source_to_visual_row(6)
            assert wrapped_row > 6
            assert view.scroll_y == wrapped_row
            assert previous.disabled is True
            assert next_change.disabled is False

    asyncio.run(exercise())


def test_requesting_a_diff_disables_navigation_until_it_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = FileEntry("example.py", Side.UNSTAGED, "M")
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    monkeypatch.setattr(GitPaneApp, "load_diff", lambda *_: None)

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            app.apply_diff_view(
                DiffView(tuple(Text(str(index)) for index in range(40)), (2, 20)),
                app.request_id,
            )
            await pilot.pause()
            assert app.query_one("#next-change", Button).disabled is False

            app.request_diff(entry)

            assert app.query_one("#previous-change", Button).disabled is True
            assert app.query_one("#next-change", Button).disabled is True

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
            app.apply_diff_view(DiffView(lines, ()), app.request_id)
            await pilot.pause()
            view.focus()

            await pilot.press("down")
            assert view.scroll_y == 1

            page_height = view.scrollable_content_region.height
            await pilot.press("pagedown")
            assert view.scroll_y == 1 + page_height

            scrollbar = view.vertical_scrollbar
            assert await pilot.click(scrollbar, offset=(0, scrollbar.size.height - 1))
            await pilot.pause()
            assert view.scroll_y == view.max_scroll_y

            await pilot.press("right")
            assert view.scroll_x == 1

            # Check the end of a long line without hundreds of simulated keys.
            view.scroll_to(x=view.max_scroll_x - 1, animate=False)
            await pilot.pause()
            for _ in range(2):
                await pilot.press("right")
                assert view.scroll_x == view.max_scroll_x

    asyncio.run(exercise())


def test_diff_request_and_refresh_clear_viewer(
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
            lines = tuple(Text(f"{row:03} " + "x" * 120) for row in range(80))

            assert view.display is True
            app.request_diff(entry)
            assert view.loading is True

            app.apply_diff_view(DiffView(lines, (17,)), app.request_id)
            await pilot.pause()
            assert app.diff_view == DiffView(lines, (17,))
            assert view.lines == lines
            assert view.scroll_offset == (0, 13)
            assert view.loading is False

            await pilot.press("w")
            await pilot.pause()
            assert view.wrapped is True
            view.scroll_to(0, 20, animate=False)
            app.request_diff(entry)
            assert view.loading is True

            await pilot.press("r")
            await pilot.pause()
            assert app.diff_view is None
            assert view.lines == ()
            assert view.scroll_offset == (0, 0)
            assert view.loading is False

            await pilot.press("w")
            await pilot.pause()
            assert view.display is True
            assert view.wrapped is False

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

            changes = () if first_change is None else (first_change,)
            app.apply_diff_view(DiffView(lines, changes), app.request_id)
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
                DiffView(tuple(Text("old " + "x" * 120) for _ in range(80)), (0,)),
                app.request_id,
            )
            await pilot.pause()
            view.scroll_to(20, 30, animate=False)
            await pilot.pause()

            replacement = tuple(Text(f"new {index}") for index in range(80))
            generation = view.document_generation
            app.apply_diff_view(DiffView(replacement, (9,)), app.request_id)
            await pilot.pause()

            assert view.lines == replacement
            assert view.document_generation == generation + 1
            assert view.scroll_offset == (0, 5)

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
            lines = tuple(Text(f"{index:03} " + "x" * 120) for index in range(100))
            app.apply_diff_view(DiffView(lines, ()), app.request_id)
            await pilot.pause()
            view.scroll_to(20, 30, animate=False)
            await pilot.pause()
            unwrapped_progress = view.scroll_y / view.max_scroll_y

            await pilot.press("w")
            await pilot.pause()

            assert view.scroll_x == 0
            assert view.scroll_y / view.max_scroll_y == pytest.approx(
                unwrapped_progress, abs=1 / view.max_scroll_y
            )

            view.scroll_to(0, view.max_scroll_y / 2, animate=False)
            await pilot.pause()
            wrapped_progress = view.scroll_y / view.max_scroll_y

            await pilot.press("w")
            await pilot.pause()

            assert view.scroll_x == 0
            assert view.scroll_y / view.max_scroll_y == pytest.approx(
                wrapped_progress, abs=1 / view.max_scroll_y
            )

    asyncio.run(exercise())


def test_loading_a_new_diff_while_wrapped_updates_the_viewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(80, 12)) as pilot:
            await pilot.press("w")
            await pilot.pause()
            view = app.query_one("#diff-view", CodeView)
            view.loading = True
            lines = tuple(Text(f"new {index}") for index in range(40))

            app.apply_diff_view(DiffView(lines, (17,)), app.request_id)
            await pilot.pause()

            assert view.lines == lines
            assert view.scroll_y == view.source_to_visual_row(13)
            assert view.loading is False

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
                tuple(Text(f"new {index} " + "x" * 120) for index in range(100)),
                (20,),
            )
            app.apply_diff_view(newer, current)
            await pilot.pause()
            view = app.query_one("#diff-view", CodeView)
            view.scroll_to(20, 30, animate=False)
            await pilot.pause()
            await pilot.press("w")
            await pilot.pause()
            view.scroll_to(0, 10, animate=False)
            view.loading = True
            state = (
                app.diff_view,
                view.lines,
                view.document_generation,
                view.scroll_offset,
            )

            app.apply_diff_view(DiffView((Text("old"),), (0,)), current - 1)

            assert (
                app.diff_view,
                view.lines,
                view.document_generation,
                view.scroll_offset,
            ) == state
            assert view.loading is True

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
            scroll = app.query_one("#preview-view", CodeView)
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
            assert isinstance(app.query_one("#diff-view"), CodeView)

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


def test_status_refresh_runs_git_off_the_event_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    started = threading.Event()
    release = threading.Event()
    worker_threads: list[int] = []

    def slow_status(root: Path) -> RepoState:
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(timeout=2)
        return RepoState(root, [], [], "worker")

    monkeypatch.setattr("gitpane.app.git.status", slow_status)

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            event_thread = threading.get_ident()
            assert await asyncio.to_thread(started.wait, 1)

            await pilot.pause()
            assert len(worker_threads) == 1
            assert worker_threads[0] != event_thread
            assert app.query_one("#staged-list", ListView).loading is True

            release.set()
            await app.workers.wait_for_complete()
            assert str(app.query_one("#branch-status", Static).content) == (
                "Branch: worker"
            )

    asyncio.run(exercise())


def test_refresh_apply_methods_ignore_stale_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "gitpane.app.git.status", lambda root: RepoState(root, [], [], "current")
    )
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test():
            stale_status = RepoState(
                tmp_path,
                [FileEntry("stale.txt", Side.STAGED, "M")],
                [],
                "stale",
            )
            await app.apply_status(stale_status, app.status_request_id - 1)
            app.apply_history(
                [Commit("stale", "stale", None, "Stale")],
                app.history_request_id - 1,
            )
            app.apply_files([Path("stale.txt")], app.files_request_id - 1)

            assert str(app.query_one("#branch-status", Static).content) == (
                "Branch: current"
            )
            assert not app.query_one("#staged-list", ListView).children
            assert not app.query_one("#commit-tree", Tree).root.children
            assert not app.query_one("#files-tree", Tree).root.children

    asyncio.run(exercise())


def test_repeated_status_refreshes_do_not_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    first_started = threading.Event()
    release_first = threading.Event()
    calls: list[int] = []
    active = 0
    max_active = 0

    def slow_status(root: Path) -> RepoState:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        call = len(calls) + 1
        calls.append(call)
        if call == 1:
            first_started.set()
            assert release_first.wait(timeout=2)
        active -= 1
        return RepoState(root, [], [], f"refresh-{call}")

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            monkeypatch.setattr("gitpane.app.git.status", slow_status)

            app.refresh_status()
            assert await asyncio.to_thread(first_started.wait, 1)
            app.refresh_status()
            await pilot.pause()
            assert calls == [1]
            assert max_active == 1

            release_first.set()
            await app.workers.wait_for_complete()
            assert calls == [1, 2]
            assert max_active == 1
            assert str(app.query_one("#branch-status", Static).content) == (
                "Branch: refresh-2"
            )

    asyncio.run(exercise())


def test_mutations_are_serialized_in_request_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    first_started = threading.Event()
    release_first = threading.Event()
    status_started = threading.Event()
    release_status = threading.Event()
    calls: list[str] = []
    status_calls = 0
    active = 0
    max_active = 0
    guard = threading.Lock()

    def slow_status(root: Path) -> RepoState:
        nonlocal status_calls
        status_calls += 1
        if status_calls == 2:
            status_started.set()
            assert release_status.wait(timeout=2)
        return RepoState(root, [], [])

    def slow_stage(_: Path, *paths: str) -> None:
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
            calls.append(paths[0])
        if paths[0] == "one.txt":
            first_started.set()
            assert release_first.wait(timeout=2)
        with guard:
            active -= 1

    monkeypatch.setattr("gitpane.app.git.stage", slow_stage)
    monkeypatch.setattr("gitpane.app.git.status", slow_status)

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            app.apply_entries("stage", [FileEntry("one.txt", Side.UNSTAGED, "M")])
            assert await asyncio.to_thread(first_started.wait, 1)
            app.apply_entries("stage", [FileEntry("two.txt", Side.UNSTAGED, "M")])

            await pilot.pause()
            assert calls == ["one.txt"]
            assert max_active == 1

            release_first.set()
            assert await asyncio.to_thread(status_started.wait, 1)
            await pilot.pause()
            assert calls == ["one.txt"]

            release_status.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert calls == ["one.txt", "two.txt"]
            assert max_active == 1

    asyncio.run(exercise())


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


def test_discard_files_restores_tracked_and_cleans_untracked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path("/repo")
    calls: list[tuple[str, Path, tuple[str, ...]]] = []
    monkeypatch.setattr(
        "gitpane.app.git.restore",
        lambda received_root, *paths: calls.append(("restore", received_root, paths)),
    )
    monkeypatch.setattr(
        "gitpane.app.git.clean",
        lambda received_root, *paths: calls.append(("clean", received_root, paths)),
    )

    discard_files(
        root,
        [
            FileEntry("tracked.txt", Side.UNSTAGED, "M"),
            FileEntry("new.txt", Side.UNSTAGED, "?"),
        ],
    )

    assert calls == [
        ("restore", root, ("tracked.txt",)),
        ("clean", root, ("new.txt",)),
    ]


def test_status_actions_support_single_bulk_and_confirmed_discard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = FileEntry("staged.txt", Side.STAGED, "M")
    modified = FileEntry("modified.txt", Side.UNSTAGED, "M")
    untracked = FileEntry("new.txt", Side.UNSTAGED, "?")
    calls: list[tuple[str, tuple[str, ...]]] = []
    requested: list[FileEntry] = []

    monkeypatch.setattr(
        "gitpane.app.git.status",
        lambda root: RepoState(root, [staged], [modified, untracked], "main"),
    )
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    monkeypatch.setattr(
        GitPaneApp,
        "load_diff",
        lambda _self, entry, _token: requested.append(entry),
    )
    monkeypatch.setattr(
        "gitpane.app.git.stage",
        lambda _root, *paths: calls.append(("stage", paths)),
    )
    monkeypatch.setattr(
        "gitpane.app.git.unstage",
        lambda _root, *paths: calls.append(("unstage", paths)),
    )
    monkeypatch.setattr(
        "gitpane.app.git.restore",
        lambda _root, *paths: calls.append(("restore", paths)),
    )
    monkeypatch.setattr(
        "gitpane.app.git.clean",
        lambda _root, *paths: calls.append(("clean", paths)),
    )

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            staged_item = app.query_one("#staged-list", ListView).children[0]
            assert isinstance(staged_item, FileItem)
            assert staged_item.query_one(".unstage-action", Button).tooltip == (
                "Unstage Changes"
            )

            await pilot.click(staged_item, offset=(1, 0))
            await pilot.pause()
            assert staged_item.checked is True
            assert app.selection is None
            assert requested == []
            assert str(staged_item.query_one(".file-label", Static).content).startswith(
                "[x]"
            )
            bulk_unstage = app.query_one("#unstage-selected", Button)
            assert bulk_unstage.disabled is False
            assert app.query_one("#staged-actions").has_class("has-selection")

            assert await pilot.click(bulk_unstage)
            await pilot.pause()
            assert calls == [("unstage", ("staged.txt",))]

            unstaged_list = app.query_one("#unstaged-list", ListView)
            modified_item = unstaged_list.children[0]
            assert isinstance(modified_item, FileItem)
            await pilot.hover(modified_item)
            await pilot.pause()
            stage_button = modified_item.query_one(".stage-action", Button)
            await pilot.hover(stage_button)
            await pilot.pause()
            assert modified_item.has_class("-hovered")
            assert str(modified_item.query_one(".file-actions").styles.display) == (
                "block"
            )
            assert await pilot.click(stage_button)
            await pilot.pause()
            assert calls[-1] == ("stage", ("modified.txt",))

            unstaged_list = app.query_one("#unstaged-list", ListView)
            for item in unstaged_list.children:
                assert isinstance(item, FileItem)
                item.toggle_checked()
            await pilot.pause()
            assert await pilot.click("#discard-selected")
            await pilot.pause()
            assert isinstance(app.screen, DiscardScreen)
            message = app.screen.query_one("#discard-message", Static)
            assert "Untracked files will be permanently deleted" in str(message.content)
            assert app.screen.focused is app.screen.query_one("#cancel-discard")

            assert await pilot.click("#confirm-discard")
            await pilot.pause()
            assert calls[-2:] == [
                ("restore", ("modified.txt",)),
                ("clean", ("new.txt",)),
            ]

            call_count = len(calls)
            app.request_discard([modified])
            await pilot.pause()
            assert await pilot.click("#cancel-discard")
            await pilot.pause()
            assert len(calls) == call_count

    asyncio.run(exercise())


def test_unsupported_status_entries_are_visible_and_not_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reason = "Conflict (UU) resolution is not supported."
    entry = FileEntry("conflict.txt", Side.UNSTAGED, "U", reason)
    loaded: list[FileEntry] = []
    monkeypatch.setattr(
        "gitpane.app.git.status", lambda root: RepoState(root, [], [entry], "main")
    )
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    monkeypatch.setattr(
        GitPaneApp, "load_diff", lambda _self, selected, _token: loaded.append(selected)
    )

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            item = app.query_one("#unstaged-list", ListView).children[0]
            assert isinstance(item, FileItem)
            assert str(item.query_one(".file-label", Static).content) == (
                "[!] U conflict.txt - " + reason
            )
            assert list(item.query(Button)) == []

            item.toggle_checked()
            await pilot.pause()
            assert item.checked is False
            assert app.query_one("#stage-selected", Button).disabled is True
            assert app.query_one("#discard-selected", Button).disabled is True

            await pilot.click(item, offset=(1, 0))
            await pilot.pause()
            assert app.selection == entry
            assert loaded == []
            assert app.query_one("#diff-view", CodeView).lines == (Text(reason),)

    asyncio.run(exercise())


def test_git_failures_are_reported_without_terminating_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = subprocess.CalledProcessError(
        128,
        ["git", "status"],
        stderr="fatal: index.lock already exists\n",
    )
    notifications: list[tuple[str, str | None, str]] = []

    def fail_status(_: Path) -> RepoState:
        raise error

    def record_notification(
        _self: GitPaneApp,
        message: str,
        *,
        title: str | None = None,
        severity: str = "information",
        **_: object,
    ) -> None:
        notifications.append((message, title, severity))

    monkeypatch.setattr("gitpane.app.git.status", fail_status)
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    monkeypatch.setattr(GitPaneApp, "notify", record_notification)

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test():
            assert app.query_one("#branch-status", Static)

    asyncio.run(exercise())

    assert notifications == [
        (
            "fatal: index.lock already exists",
            "Could not refresh status",
            "error",
        )
    ]


def test_diff_failure_clears_loading_and_reports_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    notifications: list[str] = []

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test():
            monkeypatch.setattr(
                app,
                "notify",
                lambda message, **_: notifications.append(message),
            )
            app.query_one("#diff-view", CodeView).loading = True
            app.apply_diff_error(
                subprocess.CalledProcessError(
                    1, ["git", "diff"], stderr="fatal: diff failed\n"
                ),
                app.request_id,
            )

            assert app.query_one("#diff-view", CodeView).loading is False

    asyncio.run(exercise())

    assert notifications == ["fatal: diff failed"]


def test_status_failure_invalidates_diff_and_clears_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    def fail_status(_: Path) -> RepoState:
        raise subprocess.CalledProcessError(128, ["git", "status"])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test():
            monkeypatch.setattr(app, "notify", lambda *_, **__: None)
            monkeypatch.setattr("gitpane.app.git.status", fail_status)
            app.query_one("#diff-view", CodeView).loading = True

            app.refresh_status()
            await app.workers.wait_for_complete()

            assert app.query_one("#diff-view", CodeView).loading is False

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(-1, False), (0, True), (2, True), (3, False)],
)
def test_is_prefix_offset_includes_only_checkbox_columns(
    offset: int, expected: bool
) -> None:
    assert is_prefix_offset(offset) is expected
