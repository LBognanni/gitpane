import asyncio
import threading
from pathlib import Path

import pytest
from textual.widgets import ListView, Static, Tree

from gitpane.app import GitPaneApp
from gitpane.model import Commit, FileEntry, RepoState, Side
from gitpane.widgets import FileItem


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


def test_superseded_refresh_results_are_never_displayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refresh superseded while running never reaches the panes."""
    started = {
        "status": [threading.Event(), threading.Event()],
        "commits": [threading.Event(), threading.Event()],
        "files": [threading.Event(), threading.Event()],
    }
    release_older = threading.Event()
    release_newer = threading.Event()
    calls = {"status": 0, "commits": 0, "files": 0}

    def status(root: Path) -> RepoState:
        calls["status"] += 1
        started["status"][calls["status"] - 1].set()
        if calls["status"] == 1:
            assert release_older.wait(timeout=5)
            return RepoState(
                root, [FileEntry("old.txt", Side.STAGED, "M")], [], "older"
            )
        assert release_newer.wait(timeout=5)
        return RepoState(root, [], [FileEntry("new.txt", Side.UNSTAGED, "M")], "newer")

    def commits(_: Path) -> list[Commit]:
        calls["commits"] += 1
        started["commits"][calls["commits"] - 1].set()
        if calls["commits"] == 1:
            assert release_older.wait(timeout=5)
            return [Commit("a" * 40, "aaaaaaa", None, "Older commit")]
        assert release_newer.wait(timeout=5)
        return [Commit("b" * 40, "bbbbbbb", None, "Newer commit")]

    def files(_: Path) -> list[str]:
        calls["files"] += 1
        started["files"][calls["files"] - 1].set()
        if calls["files"] == 1:
            assert release_older.wait(timeout=5)
            return ["older.txt"]
        assert release_newer.wait(timeout=5)
        return ["newer.txt"]

    monkeypatch.setattr("gitpane.app.git.status", status)
    monkeypatch.setattr("gitpane.app.git.commits", commits)
    monkeypatch.setattr("gitpane.app.git.files", files)

    def visible_text(app: GitPaneApp) -> str:
        """Return the text the repository panes currently show."""
        parts = [
            str(app.query_one("#branch-status", Static).content),
            *(item.entry.path for item in app.query(FileItem)),
        ]
        for tree_id in ("#commit-tree", "#files-tree"):
            parts.extend(
                str(node.label) for node in app.query_one(tree_id, Tree).root.children
            )
        return "\n".join(parts)

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            for first, _ in started.values():
                assert await asyncio.to_thread(first.wait, 5)

            app.refresh_status()
            app.refresh_history()
            app.refresh_files()
            await pilot.pause()

            release_older.set()
            for _, second in started.values():
                assert await asyncio.to_thread(second.wait, 5)
            await pilot.pause()
            await pilot.pause()

            superseded = visible_text(app)
            assert "older" not in superseded
            assert "old.txt" not in superseded
            assert "Older commit" not in superseded

            release_newer.set()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert str(app.query_one("#branch-status", Static).content) == (
                "Branch: newer"
            )
            staged = app.query_one("#staged-list", ListView)
            unstaged = app.query_one("#unstaged-list", ListView)
            assert not staged.children
            assert [item.entry.path for item in unstaged.query(FileItem)] == ["new.txt"]
            commit_labels = [
                str(node.label)
                for node in app.query_one("#commit-tree", Tree).root.children
            ]
            assert len(commit_labels) == 1
            assert "Newer commit" in commit_labels[0]
            file_labels = [
                str(node.label)
                for node in app.query_one("#files-tree", Tree).root.children
            ]
            assert len(file_labels) == 1
            assert "newer.txt" in file_labels[0]

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
