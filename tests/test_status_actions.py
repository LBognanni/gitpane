import asyncio
import subprocess
from pathlib import Path

import pytest
from rich.text import Text
from textual.widgets import Button, ListView, Static

from gitpane.app import (
    DiscardScreen,
    FileItem,
    GitPaneApp,
    discard_files,
    format_file_label,
    is_prefix_offset,
    toggle_file,
)
from gitpane.model import FileEntry, RepoState, Side
from gitpane.widgets import CodeView


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
