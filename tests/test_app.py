import asyncio
from pathlib import Path

import pytest
from rich.text import Text
from textual.content import Content
from textual.widgets import ListView, Static, TabbedContent, Tree

from gitpane.app import GitPaneApp, format_commit_label
from gitpane.diff_view import DiffView
from gitpane.model import Commit, CommitFile, FileEntry, RepoState, Side
from gitpane.screens.shortcuts import ShortcutScreen, claim_first_launch
from gitpane.widgets import CodeView


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

    monkeypatch.setattr(
        "gitpane.screens.shortcuts.user_state_path", fake_user_state_path
    )

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

            app.diff_pane.apply(
                DiffView(tuple(Text(str(index)) for index in range(40)), (5, 20)),
                app.diff_pane.request_id,
            )
            await pilot.pause()
            await pilot.press("n")
            assert app.diff_pane.change_index == 1
            await pilot.press("p")
            assert app.diff_pane.change_index == 0

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
        "gitpane.app.git.diff",
        lambda _root, _entry: (
            "diff --git a/report.txt b/report.txt\n--- a/report.txt\n"
            "+++ b/report.txt\n@@ -1,2 +1,2 @@\n context line\n"
            "-old report text\n+new report text\n"
        ),
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

            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.diff_pane.selection == entry
            diff_title = app.query_one("#diff-title", Static).render()
            assert isinstance(diff_title, Content)
            assert diff_title.plain == entry.path
            assert diff_title.spans == []
            diff_view = app.query_one("#diff-view", CodeView)
            displayed = "\n".join(
                diff_view.render_line(y).text for y in range(diff_view.size.height)
            )
            assert "new report text" in displayed
            assert "old report text" in displayed

    asyncio.run(exercise())
