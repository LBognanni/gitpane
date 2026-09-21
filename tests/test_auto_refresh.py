import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import ListView, Static

import gitpane.app as app_module
from gitpane.app import GitPaneApp
from gitpane.model import FileEntry, RepoState, Side
from gitpane.watcher import Invalidation
from gitpane.widgets import CodeView, FileItem


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


def entry(path: str, status: str = "M", side: Side = Side.UNSTAGED) -> FileEntry:
    return FileEntry(path, side, status)


class Repo:
    """Mutable mocked repository whose diff text encodes a version counter."""

    def __init__(self, unstaged: list[FileEntry], staged: list[FileEntry]) -> None:
        self.unstaged = unstaged
        self.staged = staged
        self.calls = 0
        self.version = 1

    def status(self, root: Path) -> RepoState:
        self.calls += 1
        return RepoState(root, list(self.staged), list(self.unstaged), "main")

    def diff(self, _: Path, target: FileEntry) -> str:
        body = [f" context {i}" for i in range(20)]
        body[3] = f"-old\n+{target.path} version {self.version}"
        return (
            f"diff --git a/{target.path} b/{target.path}\n"
            f"--- a/{target.path}\n+++ b/{target.path}\n"
            "@@ -1,20 +1,20 @@\n" + "\n".join(body) + "\n"
        )


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> Repo:
    repo = Repo([entry("a.txt"), entry("b.txt"), entry("c.txt")], [])
    monkeypatch.setattr("gitpane.app.git.status", repo.status)
    monkeypatch.setattr("gitpane.app.git.diff", repo.diff)
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    return repo


def labels(app: GitPaneApp, selector: str) -> list[str]:
    view = app.query_one(selector, ListView)
    return [
        str(item.query_one(".file-label", Static).content) for item in view.children
    ]


def highlighted(app: GitPaneApp, selector: str) -> str:
    item = app.query_one(selector, ListView).highlighted_child
    assert isinstance(item, FileItem)
    return item.entry.path


def diff_text(app: GitPaneApp) -> str:
    view = app.query_one("#diff-view", CodeView)
    return "\n".join(view.render_line(y).text for y in range(view.size.height))


async def refresh(
    app: GitPaneApp, pilot: Pilot[None], repo: Repo, queue: asyncio.Queue[Invalidation]
) -> None:
    """Deliver an event and wait for its automatic refresh to be applied."""
    before = repo.calls
    queue.put_nowait(edit("b.txt"))
    while repo.calls == before:
        await pilot.pause()
    assert app.auto_refresh_task is not None
    await app.auto_refresh_task
    await app.workers.wait_for_complete()
    await pilot.pause()


async def select_checked_b(app: GitPaneApp, pilot: Pilot[None]) -> None:
    await app.workers.wait_for_complete()
    await pilot.press("j", "space", "enter")
    await app.workers.wait_for_complete()
    await pilot.pause()


def test_equal_status_leaves_lists_selection_focus_and_diff_untouched(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            unstaged = app.query_one("#unstaged-list", ListView)
            items = list(unstaged.children)
            focused = app.focused
            assert focused is unstaged
            assert "b.txt version 1" in diff_text(app)

            repo.version = 2
            queue.put_nowait(
                Invalidation(status=True, changed_paths=frozenset({Path("z")}))
            )
            before = repo.calls
            while repo.calls == before:
                await pilot.pause()
            assert app.auto_refresh_task is not None
            await app.auto_refresh_task
            await pilot.pause()

            assert list(unstaged.children) == items
            assert labels(app, "#unstaged-list")[1] == "[x] M b.txt"
            assert highlighted(app, "#unstaged-list") == "b.txt"
            assert app.focused is unstaged
            assert unstaged.loading is False
            assert "b.txt version 1" in diff_text(app)

    asyncio.run(exercise())


def test_changed_status_updates_lists_and_restores_surviving_state(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            await pilot.press("j", "space", "k")
            assert labels(app, "#unstaged-list") == [
                "[ ] M a.txt",
                "[x] M b.txt",
                "[x] M c.txt",
            ]

            # a.txt is staged externally, c.txt disappears, d.txt is new,
            # and b.txt changes from M to D.
            repo.staged = [entry("a.txt", side=Side.STAGED)]
            repo.unstaged = [entry("b.txt", "D"), entry("d.txt", "?")]
            await refresh(app, pilot, repo, queue)

            assert labels(app, "#staged-list") == ["[ ] M a.txt"]
            assert labels(app, "#unstaged-list") == ["[x] D b.txt", "[ ] ? d.txt"]
            assert highlighted(app, "#unstaged-list") == "b.txt"
            assert app.focused is app.query_one("#unstaged-list")
            assert app.query_one("#stage-selected").disabled is False
            assert app.query_one("#unstaged-list").loading is False

    asyncio.run(exercise())


def test_background_refresh_does_not_steal_focus_or_select_first_entry(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("j")
            app.query_one("#commit-tree").focus()
            repo.staged = [entry("x.txt", side=Side.STAGED)]
            await refresh(app, pilot, repo, queue)

            assert labels(app, "#staged-list") == ["[ ] M x.txt"]
            assert app.focused is app.query_one("#commit-tree")
            assert highlighted(app, "#unstaged-list") == "b.txt"

    asyncio.run(exercise())


def test_equal_status_with_changed_selected_path_reloads_diff_only(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            unstaged = app.query_one("#unstaged-list", ListView)
            items = list(unstaged.children)

            repo.version = 2
            queue.put_nowait(edit("a.txt"))
            before = repo.calls
            while repo.calls == before:
                await pilot.pause()
            assert app.auto_refresh_task is not None
            await app.auto_refresh_task
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "b.txt version 1" in diff_text(app)

            await refresh(app, pilot, repo, queue)

            assert "b.txt version 2" in diff_text(app)
            assert list(unstaged.children) == items
            assert labels(app, "#unstaged-list")[1] == "[x] M b.txt"

    asyncio.run(exercise())


def test_changed_status_keeps_restored_highlight_visible_in_scrolled_list(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()
    repo.unstaged = [entry(f"f{i:02}.txt") for i in range(40)]

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            unstaged = app.query_one("#unstaged-list", ListView)
            unstaged.index = 30
            await pilot.pause()
            assert unstaged.scroll_y > 0

            repo.unstaged = repo.unstaged[10:]
            await refresh(app, pilot, repo, queue)

            assert highlighted(app, "#unstaged-list") == "f30.txt"
            item = unstaged.highlighted_child
            assert item is not None
            top = unstaged.scroll_y
            assert top > 0
            assert top <= item.virtual_region.y
            assert (
                item.virtual_region.bottom
                <= top + unstaged.scrollable_content_region.height
            )

    asyncio.run(exercise())
