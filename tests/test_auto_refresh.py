import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from textual.widgets import Static

import gitpane.app as app_module
from gitpane.app import GitPaneApp
from gitpane.model import FileEntry, RepoState, Side
from gitpane.watcher import Invalidation


class FakeGit:
    """Status adapter whose calls block until released, recording overlap."""

    def __init__(self) -> None:
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.started = [threading.Event() for _ in range(10)]
        self.release = [threading.Event() for _ in range(10)]
        self.release[0].set()
        self.fail: set[int] = set()

    def status(self, root: Path) -> RepoState:
        index = self.calls
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started[index].set()
        assert self.release[index].wait(timeout=5)
        self.active -= 1
        if index in self.fail:
            raise OSError("git failed")
        return RepoState(root, [], [], f"call {index}")


@pytest.fixture
def fake_git(monkeypatch: pytest.MonkeyPatch) -> FakeGit:
    fake = FakeGit()
    monkeypatch.setattr("gitpane.app.git.status", fake.status)
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    return fake


def make_watcher() -> tuple[
    asyncio.Queue[Invalidation], Callable[[Path], AsyncIterator[Invalidation]]
]:
    queue: asyncio.Queue[Invalidation] = asyncio.Queue()

    async def watch(_: Path) -> AsyncIterator[Invalidation]:
        while True:
            yield await queue.get()

    return queue, watch


def branch(app: GitPaneApp) -> str:
    return str(app.query_one("#branch-status", Static).content)


async def wait(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 5)


EDIT = Invalidation(status=True, changed_paths=frozenset({Path("a.txt")}))


def test_burst_during_read_produces_one_follow_up(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()

            queue.put_nowait(EDIT)
            await wait(fake_git.started[1])
            for _ in range(5):
                queue.put_nowait(EDIT)
            await pilot.pause()
            assert fake_git.calls == 2

            fake_git.release[1].set()
            fake_git.release[2].set()
            await wait(fake_git.started[2])
            await pilot.pause()
            assert app.auto_refresh_task is not None
            await app.auto_refresh_task
            assert app.auto_pending is None
            assert fake_git.calls == 3
            assert fake_git.max_active == 1
            assert branch(app) == "Branch: call 2"

    asyncio.run(exercise())


def test_events_without_status_invalidation_do_not_refresh(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()
            queue.put_nowait(Invalidation())
            await pilot.pause()
            assert fake_git.calls == 1

    asyncio.run(exercise())


def test_manual_refresh_supersedes_older_automatic_result(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()

            queue.put_nowait(EDIT)
            await wait(fake_git.started[1])
            app.refresh_status()
            await pilot.pause()

            fake_git.release[1].set()
            fake_git.release[2].set()
            await wait(fake_git.started[2])
            await app.workers.wait_for_complete()
            assert branch(app) == "Branch: call 2"
            assert fake_git.max_active == 1

    asyncio.run(exercise())


def test_mutation_is_not_interleaved_with_automatic_status(
    tmp_path: Path, fake_git: FakeGit, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()
    order: list[str] = []
    monkeypatch.setattr("gitpane.app.git.stage", lambda *_: order.append("stage"))
    original = fake_git.status

    def status(root: Path) -> RepoState:
        order.append("status")
        return original(root)

    monkeypatch.setattr("gitpane.app.git.status", status)

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()
            order.clear()

            queue.put_nowait(EDIT)
            await wait(fake_git.started[1])
            app.apply_entries("stage", [FileEntry("a.txt", Side.UNSTAGED, "M")])
            await pilot.pause()
            assert order == ["status"]

            fake_git.release[1].set()
            fake_git.release[2].set()
            await app.workers.wait_for_complete()
            assert order[:3] == ["status", "stage", "status"]
            assert fake_git.max_active == 1

    asyncio.run(exercise())


def test_unmount_cancels_watcher_and_refresh(tmp_path: Path, fake_git: FakeGit) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test():
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()
            queue.put_nowait(EDIT)
            await wait(fake_git.started[1])
        assert app.watch_task is not None and app.watch_task.done()
        assert app.auto_refresh_task is not None and app.auto_refresh_task.done()
        assert len(app._notifications) == 0
        for release in fake_git.release:
            release.set()

    asyncio.run(exercise())


def test_watcher_setup_failure_notifies_once_and_manual_refresh_works(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    async def failing(_: Path) -> AsyncIterator[Invalidation]:
        raise OSError("inotify watch limit reached")
        yield Invalidation()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=failing)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()
            await pilot.pause()
            messages = [n.message for n in app._notifications]
            assert len(messages) == 1
            assert "could not start" in messages[0]
            assert "Press r" in messages[0]

            fake_git.release[1].set()
            await pilot.press("r")
            await wait(fake_git.started[1])
            await app.workers.wait_for_complete()
            assert branch(app) == "Branch: call 1"

    asyncio.run(exercise())


class RecordingApp(GitPaneApp):
    """Records the invalidation passed with each applied status."""

    CSS_PATH = Path(app_module.__file__).with_name("app.tcss")
    applied: list[Invalidation | None]

    async def apply_status(
        self,
        state: RepoState,
        token: int,
        invalidation: Invalidation | None = None,
    ) -> None:
        if not hasattr(self, "applied"):
            self.applied = []
        if token == self.status_request_id:
            self.applied.append(invalidation)
        await super().apply_status(state, token, invalidation)


def edit(name: str) -> Invalidation:
    return Invalidation(status=True, changed_paths=frozenset({Path(name)}))


def test_invalidation_survives_a_superseded_automatic_read(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = RecordingApp(tmp_path, watch_source=watch)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()
            app.applied.clear()

            app.refresh_status()
            await wait(fake_git.started[1])
            queue.put_nowait(edit("a.txt"))
            while app.auto_refresh_task is None:
                await pilot.pause()
            app.refresh_status()
            await pilot.pause()
            for release in fake_git.release:
                release.set()
            await app.workers.wait_for_complete()
            await app.auto_refresh_task

            assert [i for i in app.applied if i is not None] == [edit("a.txt")]

    asyncio.run(exercise())


def test_invalidation_survives_a_failed_automatic_read(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    queue, watch = make_watcher()
    fake_git.fail = {1}
    fake_git.release[1].set()
    fake_git.release[2].set()

    async def exercise() -> None:
        app = RecordingApp(tmp_path, watch_source=watch)
        async with app.run_test():
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()
            app.applied.clear()

            queue.put_nowait(edit("a.txt"))
            await wait(fake_git.started[1])
            assert app.auto_refresh_task is not None
            await app.auto_refresh_task
            assert fake_git.calls == 2
            assert app.applied == []

            queue.put_nowait(edit("b.txt"))
            await wait(fake_git.started[2])
            while not app.applied:
                await asyncio.sleep(0)
            assert app.applied == [
                Invalidation(
                    status=True, changed_paths=frozenset({Path("a.txt"), Path("b.txt")})
                )
            ]

    asyncio.run(exercise())


def test_automatic_request_does_not_supersede_in_flight_manual_refresh(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()

            app.refresh_status()
            await wait(fake_git.started[1])
            queue.put_nowait(EDIT)
            while app.auto_refresh_task is None:
                await pilot.pause()
            await pilot.pause()

            fake_git.release[1].set()
            await wait(fake_git.started[2])
            await pilot.pause()
            assert branch(app) == "Branch: call 1"
            assert app.query_one("#staged-list").loading is False

            fake_git.release[2].set()
            await app.auto_refresh_task
            assert branch(app) == "Branch: call 2"

    asyncio.run(exercise())


def test_watcher_failure_after_startup_notifies_once(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    async def dying(_: Path) -> AsyncIterator[Invalidation]:
        yield Invalidation()
        raise OSError("watch lost")

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=dying)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()
            assert app.watch_task is not None
            await app.watch_task
            await pilot.pause()
            messages = [n.message for n in app._notifications]
            assert len(messages) == 1
            assert "stopped" in messages[0]
            assert "Press r" in messages[0]

    asyncio.run(exercise())
