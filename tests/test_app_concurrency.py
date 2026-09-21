import asyncio
import threading
from pathlib import Path

import pytest
from textual.widgets import ListView, Static, Tree

from gitpane.app import GitPaneApp, is_current_request
from gitpane.model import Commit, FileEntry, RepoState, Side


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
