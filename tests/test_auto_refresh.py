import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import ListView, Static, Tree

import gitpane.app as app_module
from gitpane.app import GitPaneApp
from gitpane.model import Commit, CommitFile, FileEntry, RepoState, Side
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


def test_superseded_automatic_apply_does_not_reset_failure_streak(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    queue, watch = make_watcher()
    fake_git.fail = {1, 4}
    for i, release in enumerate(fake_git.release):
        if i != 2:
            release.set()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()

            queue.put_nowait(EDIT)
            await wait(fake_git.started[1])
            assert app.auto_refresh_task is not None
            await app.auto_refresh_task
            await pilot.pause()  # notify() posts a message; let the app process it
            assert len(app._notifications) == 1

            queue.put_nowait(EDIT)
            await wait(fake_git.started[2])
            app.refresh_status()
            fake_git.release[2].set()
            await app.auto_refresh_task
            await app.workers.wait_for_complete()

            queue.put_nowait(EDIT)
            await wait(fake_git.started[4])
            await app.auto_refresh_task
            await pilot.pause()
            assert len(app._notifications) == 1

    asyncio.run(exercise())


def test_unexpected_automatic_error_is_reported_and_retryable(
    tmp_path: Path, fake_git: FakeGit, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()
    for release in fake_git.release:
        release.set()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()

            def explode(*_: object) -> RepoState:
                raise ValueError("boom")

            monkeypatch.setattr("gitpane.app.git.status", explode)
            queue.put_nowait(EDIT)
            while not app._notifications:
                await asyncio.sleep(0)
            await pilot.pause()
            assert "boom" in next(n.message for n in app._notifications)

            monkeypatch.setattr("gitpane.app.git.status", fake_git.status)
            queue.put_nowait(EDIT)
            while branch(app) != "Branch: call 1":
                await asyncio.sleep(0)

    asyncio.run(exercise())


def test_unexpected_watcher_error_notifies_stopped(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    async def dying(_: Path) -> AsyncIterator[Invalidation]:
        yield Invalidation()
        raise ValueError("watch broke")

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=dying)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()
            assert app.watch_task is not None
            await app.watch_task
            await pilot.pause()
            messages = [n.message for n in app._notifications]
            assert len(messages) == 1 and "stopped" in messages[0]

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
            for _ in range(50):  # scroll-to-highlight lands after layout
                await pilot.pause()
                if unstaged.scroll_y > 0:
                    break
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


MISSING = "The selected change is no longer present."


async def settle(
    app: GitPaneApp,
    pilot: Pilot[None],
    repo: Repo,
    event: Invalidation,
    queue: asyncio.Queue[Invalidation],
) -> None:
    before = repo.calls
    queue.put_nowait(event)
    while repo.calls == before:
        await pilot.pause()
    assert app.auto_refresh_task is not None
    await app.auto_refresh_task
    await app.workers.wait_for_complete()
    await pilot.pause()


def test_editing_selected_unstaged_path_reloads_but_other_paths_do_not(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            repo.version = 2
            await settle(app, pilot, repo, edit("a.txt"), queue)
            assert "b.txt version 1" in diff_text(app)

            await settle(app, pilot, repo, edit("b.txt"), queue)
            assert "b.txt version 2" in diff_text(app)
            assert app.query_one("#diff-view", CodeView).loading is False
            assert highlighted(app, "#unstaged-list") == "b.txt"

    asyncio.run(exercise())


def test_index_change_reloads_selected_staged_diff_only(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()
    repo.staged = [entry("s.txt", side=Side.STAGED)]

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "s.txt version 1" in diff_text(app)

            repo.version = 2
            await settle(app, pilot, repo, edit("s.txt"), queue)
            assert "s.txt version 1" in diff_text(app)

            index = Invalidation(status=True, index_changed=True)
            await settle(app, pilot, repo, index, queue)
            assert "s.txt version 2" in diff_text(app)

    asyncio.run(exercise())


def test_committed_selection_is_cleared_without_selecting_a_replacement(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()
    repo.staged = [entry("b.txt", side=Side.STAGED)]

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "b.txt version 1" in diff_text(app)

            # Committed: staged identity gone; unstaged b.txt (same path) remains.
            repo.staged = []
            commit = Invalidation(status=True, history=True, index_changed=True)
            await settle(app, pilot, repo, commit, queue)

            text = diff_text(app)
            assert MISSING in text
            assert "version" not in text
            assert str(app.query_one("#diff-title", Static).content) == ""

    asyncio.run(exercise())


def test_surviving_selection_stays_after_status_changes(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            repo.unstaged = [entry("b.txt", "D"), entry("d.txt", "?")]
            await settle(app, pilot, repo, edit("a.txt"), queue)
            assert "b.txt version 1" in diff_text(app)
            assert MISSING not in diff_text(app)

    asyncio.run(exercise())


def test_ref_change_refreshes_history_without_moving_focus_or_selecting(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()
    commits = [[Commit("a" * 40, "aaaaaaa", None, "first")]]
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: commits[0])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            unstaged = app.query_one("#unstaged-list", ListView)
            tree = app.query_one("#commit-tree", Tree)
            assert app.focused is unstaged
            assert len(tree.root.children) == 1

            commits[0] = [Commit("b" * 40, "bbbbbbb", "a" * 40, "second"), *commits[0]]
            await settle(
                app, pilot, repo, Invalidation(status=True, history=True), queue
            )

            assert [str(n.label) for n in tree.root.children] == [
                "second bbbbbbb",
                "first aaaaaaa",
            ]
            assert tree.loading is False
            assert app.focused is unstaged
            assert "b.txt version 1" in diff_text(app)

    asyncio.run(exercise())


def test_superseded_diff_result_cannot_replace_reconciled_state(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            started = threading.Event()
            release = threading.Event()

            def blocked(root: Path, target: FileEntry) -> str:
                started.set()
                assert release.wait(timeout=5)
                return repo.diff(root, target)

            monkeypatch.setattr("gitpane.app.git.diff", blocked)
            repo.version = 2
            queue.put_nowait(edit("b.txt"))
            await wait(started)
            assert app.auto_refresh_task is not None
            await app.auto_refresh_task

            # The change is committed while the reload is still in flight.
            repo.unstaged = [entry("a.txt"), entry("c.txt")]
            before = repo.calls
            queue.put_nowait(edit("x"))
            while repo.calls == before:
                await pilot.pause()
            await app.auto_refresh_task
            await pilot.pause()
            assert MISSING in diff_text(app)

            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert MISSING in diff_text(app)
            assert "version" not in diff_text(app)

    asyncio.run(exercise())


def test_soft_reset_history_change_reloads_selected_staged_diff(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()
    repo.staged = [entry("s.txt", side=Side.STAGED)]

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

            repo.version = 2
            head = Invalidation(status=True, history=True)
            await settle(app, pilot, repo, head, queue)
            assert "s.txt version 2" in diff_text(app)

    asyncio.run(exercise())


def test_ordinary_edit_does_not_refresh_history(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()
    calls: list[Path] = []
    monkeypatch.setattr(
        "gitpane.app.git.commits", lambda root: calls.append(root) or []
    )

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            assert len(calls) == 1
            await settle(app, pilot, repo, edit("b.txt"), queue)
            assert len(calls) == 1

    asyncio.run(exercise())


def test_quiet_reload_superseding_a_normal_request_clears_loading(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            viewer = app.query_one("#diff-view", CodeView)
            started = threading.Event()
            release = threading.Event()

            def blocked(root: Path, target: FileEntry) -> str:
                started.set()
                assert release.wait(timeout=5)
                return repo.diff(root, target)

            monkeypatch.setattr("gitpane.app.git.diff", blocked)
            app.request_diff(entry("a.txt"))
            await wait(started)
            assert viewer.loading is True

            repo.version = 2
            release.set()
            await settle(app, pilot, repo, edit("a.txt"), queue)

            assert viewer.loading is False
            assert "a.txt version 2" in diff_text(app)

    asyncio.run(exercise())


def test_quiet_reload_does_not_show_loading_while_in_flight(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            viewer = app.query_one("#diff-view", CodeView)
            started = threading.Event()
            release = threading.Event()

            def blocked(root: Path, target: FileEntry) -> str:
                started.set()
                assert release.wait(timeout=5)
                return repo.diff(root, target)

            monkeypatch.setattr("gitpane.app.git.diff", blocked)
            queue.put_nowait(edit("b.txt"))
            await wait(started)
            await pilot.pause()
            assert viewer.loading is False
            assert "b.txt version 1" in diff_text(app)
            release.set()
            await app.workers.wait_for_complete()

    asyncio.run(exercise())


def test_automatic_failure_notifies_once_per_streak_and_keeps_last_state(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()
    failing = [False]

    def status(root: Path) -> RepoState:
        if failing[0]:
            raise OSError("git failed")
        return repo.status(root)

    monkeypatch.setattr("gitpane.app.git.status", status)

    async def fail_once(app: GitPaneApp, pilot: Pilot[None]) -> None:
        queue.put_nowait(edit("b.txt"))
        await pilot.pause()
        assert app.auto_refresh_task is not None
        await app.auto_refresh_task
        await pilot.pause()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            before = labels(app, "#unstaged-list")
            assert "b.txt version 1" in diff_text(app)

            failing[0] = True
            await fail_once(app, pilot)
            await fail_once(app, pilot)
            messages = [n.message for n in app._notifications]
            assert len(messages) == 1
            assert "Automatic refresh failed" in messages[0]
            assert "Press r" in messages[0]
            assert labels(app, "#unstaged-list") == before
            assert "b.txt version 1" in diff_text(app)

            failing[0] = False
            await refresh(app, pilot, repo, queue)
            await pilot.pause()
            assert len(app._notifications) == 1

            failing[0] = True
            await fail_once(app, pilot)
            assert len(app._notifications) == 2
            assert labels(app, "#unstaged-list") == before

    asyncio.run(exercise())


def test_quiet_history_failure_warns_once_and_keeps_last_state(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()
    commits = [Commit("a" * 40, "aaaaaaa", None, "first")]
    failing = [False]

    def history(_: Path) -> list[Commit]:
        if failing[0]:
            raise OSError("log failed")
        return commits

    monkeypatch.setattr("gitpane.app.git.commits", history)

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            tree = app.query_one("#commit-tree", Tree)
            before = labels(app, "#unstaged-list")
            failing[0] = True

            for _ in range(2):
                await settle(
                    app, pilot, repo, Invalidation(status=True, history=True), queue
                )

            assert [(n.severity, n.title) for n in app._notifications] == [
                ("warning", "")
            ]
            assert "Automatic refresh failed" in next(
                n.message for n in app._notifications
            )
            assert [str(n.label) for n in tree.root.children] == ["first aaaaaaa"]
            assert tree.loading is False
            assert labels(app, "#unstaged-list") == before

    asyncio.run(exercise())


def test_index_change_reloads_a_tracked_unstaged_diff(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            repo.version = 2
            index = Invalidation(status=True, index_changed=True)
            await settle(app, pilot, repo, index, queue)
            assert "b.txt version 2" in diff_text(app)
            assert highlighted(app, "#unstaged-list") == "b.txt"

    asyncio.run(exercise())


def test_index_change_does_not_reload_an_untracked_selection(
    tmp_path: Path, repo: Repo
) -> None:
    queue, watch = make_watcher()
    repo.unstaged = [entry("a.txt"), entry("b.txt", "?"), entry("c.txt")]

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            assert "b.txt version 1" in diff_text(app)
            repo.version = 2
            index = Invalidation(status=True, index_changed=True)
            await settle(app, pilot, repo, index, queue)
            assert "b.txt version 1" in diff_text(app)

    asyncio.run(exercise())


def test_quiet_diff_failure_warns_once_and_keeps_the_old_diff(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            before = labels(app, "#unstaged-list")
            working = repo.diff

            def broken(_: Path, __: FileEntry) -> str:
                raise OSError("diff failed")

            monkeypatch.setattr("gitpane.app.git.diff", broken)
            await settle(app, pilot, repo, edit("b.txt"), queue)
            await settle(app, pilot, repo, edit("b.txt"), queue)
            notes = list(app._notifications)
            assert len(notes) == 1
            assert notes[0].severity == "warning"
            assert notes[0].title == ""
            assert "Automatic refresh failed" in notes[0].message
            assert "Press r" in notes[0].message
            assert "b.txt version 1" in diff_text(app)
            assert app.query_one("#diff-view", CodeView).loading is False
            assert labels(app, "#unstaged-list") == before

            monkeypatch.setattr("gitpane.app.git.diff", working)
            repo.version = 2
            await settle(app, pilot, repo, edit("b.txt"), queue)
            assert "b.txt version 2" in diff_text(app)
            assert len(app._notifications) == 1

            monkeypatch.setattr("gitpane.app.git.diff", broken)
            await settle(app, pilot, repo, edit("b.txt"), queue)
            assert len(app._notifications) == 2

    asyncio.run(exercise())


def test_watcher_ending_without_events_notifies_stopped(
    tmp_path: Path, fake_git: FakeGit
) -> None:
    async def ending(_: Path) -> AsyncIterator[Invalidation]:
        yield Invalidation()

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=ending)
        async with app.run_test() as pilot:
            await wait(fake_git.started[0])
            await app.workers.wait_for_complete()
            assert app.watch_task is not None
            await app.watch_task
            await pilot.pause()
            messages = [n.message for n in app._notifications]
            assert len(messages) == 1
            assert "stopped" in messages[0] and "Press r" in messages[0]

    asyncio.run(exercise())


FIRST = Commit("a" * 40, "aaaaaaa", None, "first")
SECOND = Commit("b" * 40, "bbbbbbb", "a" * 40, "second")
THIRD = Commit("c" * 40, "ccccccc", "b" * 40, "third")


def cursor_hash(tree: Tree[object]) -> str:
    node = tree.cursor_node
    assert node is not None
    assert isinstance(node.data, Commit)
    return node.data.hash


async def wait_until(pilot: Pilot[None], condition: Callable[[], bool]) -> None:
    for _ in range(100):
        if condition():
            return
        await pilot.pause()
    assert condition()


def test_unrelated_ref_event_keeps_expanded_commit_files_and_cursor(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [SECOND, FIRST])
    monkeypatch.setattr(
        "gitpane.app.git.commit_files",
        lambda _root, commit: [CommitFile("x.txt", "M", commit.hash, commit.parent)],
    )

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            tree = app.query_one("#commit-tree", Tree)
            newest, older = tree.root.children
            newest.expand()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert [str(n.label) for n in newest.children] == ["M x.txt"]
            tree.move_cursor(older)
            await pilot.pause()
            assert cursor_hash(tree) == FIRST.hash

            await settle(
                app, pilot, repo, Invalidation(status=True, history=True), queue
            )

            newest = tree.root.children[0]
            assert newest.is_expanded
            assert [str(n.label) for n in newest.children] == ["M x.txt"]
            assert cursor_hash(tree) == FIRST.hash
            assert tree.loading is False

    asyncio.run(exercise())


def test_new_commit_keeps_the_selected_commit_under_the_cursor(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()
    commits = [[SECOND, FIRST]]
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: commits[0])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await select_checked_b(app, pilot)
            tree = app.query_one("#commit-tree", Tree)
            tree.move_cursor(tree.root.children[1])
            await pilot.pause()
            assert cursor_hash(tree) == FIRST.hash
            title = str(app.query_one("#diff-title", Static).content)
            diff = diff_text(app)
            assert "b.txt version 1" in diff

            commits[0] = [THIRD, SECOND, FIRST]
            await settle(
                app, pilot, repo, Invalidation(status=True, history=True), queue
            )

            assert [str(n.label) for n in tree.root.children] == [
                "third ccccccc",
                "second bbbbbbb",
                "first aaaaaaa",
            ]
            assert tree.cursor_line == 2
            assert cursor_hash(tree) == FIRST.hash
            assert diff_text(app) == diff
            assert str(app.query_one("#diff-title", Static).content) == title

    asyncio.run(exercise())


def test_commit_files_survive_an_equal_history_refresh(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, watch = make_watcher()
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [SECOND, FIRST])
    started = threading.Event()
    release = threading.Event()

    def blocked(_root: Path, commit: Commit) -> list[CommitFile]:
        started.set()
        assert release.wait(timeout=5)
        return [CommitFile("x.txt", "M", commit.hash, commit.parent)]

    monkeypatch.setattr("gitpane.app.git.commit_files", blocked)

    async def exercise() -> None:
        app = GitPaneApp(tmp_path, watch_source=watch)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            tree = app.query_one("#commit-tree", Tree)
            newest = tree.root.children[0]
            newest.expand()
            await wait(started)

            before = repo.calls
            queue.put_nowait(Invalidation(status=True, history=True))
            while repo.calls == before:
                await pilot.pause()
            assert app.auto_refresh_task is not None
            await app.auto_refresh_task
            await wait_until(
                pilot, lambda: not any(w.group == "history" for w in app.workers)
            )
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert [str(n.label) for n in newest.children] == ["M x.txt"]
            assert tree.loading is False

    asyncio.run(exercise())


def test_manual_refresh_with_equal_history_keeps_the_commit_expanded(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo.unstaged = []
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [SECOND, FIRST])
    monkeypatch.setattr(
        "gitpane.app.git.commit_files",
        lambda _root, commit: [CommitFile("x.txt", "M", commit.hash, commit.parent)],
    )

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            tree = app.query_one("#commit-tree", Tree)
            assert tree.root.children[0].is_expanded
            assert [str(n.label) for n in tree.root.children[0].children] == ["M x.txt"]

            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()

            newest = tree.root.children[0]
            assert newest.is_expanded
            assert [str(n.label) for n in newest.children] == ["M x.txt"]

    asyncio.run(exercise())
