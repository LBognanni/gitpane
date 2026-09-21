import asyncio
import subprocess
from pathlib import Path

import pytest
from rich.text import Text
from textual import events
from textual.geometry import Offset
from textual.selection import Selection
from textual.widgets import Button, TabbedContent

from gitpane.app import DiffView, GitPaneApp, PreviewView
from gitpane.model import FileEntry, RepoState, Side
from gitpane.widgets import CodeView, JumpScrollBar, scrollbar_click_target


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
