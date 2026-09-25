import asyncio
import math
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from rich.style import Style
from rich.text import Text
from textual.color import Color
from textual.geometry import Offset
from textual.pilot import Pilot
from textual.selection import Selection
from textual.widget import Widget
from textual.widgets import Button, ListView, Static, TabbedContent, Tabs

from gitpane.app import GitPaneApp
from gitpane.diff import Row
from gitpane.diff_view import DiffView, render_diff_rows
from gitpane.model import FileEntry, RepoState, Side
from gitpane.widgets import CodeView, DiffPane, FileItem, VerticalSplitter

TEXT_FLOOR = 4.5
INDICATOR_FLOOR = 3.0
LONG_PATH = "src/" + "very_long_directory_name/" * 8 + "final_file_name.py"


def _luminance(color: Color) -> float:
    def linear(channel: int) -> float:
        value = channel / 255
        if value <= 0.04045:
            return value / 12.92
        return math.pow((value + 0.055) / 1.055, 2.4)

    return (
        0.2126 * linear(color.r) + 0.7152 * linear(color.g) + 0.0722 * linear(color.b)
    )


def _contrast(first: Color, second: Color) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _color(color: object) -> Color:
    """Convert a Rich color to an opaque Textual color."""
    return Color.from_rich_color(color).with_alpha(1)


def _colors(style: Style) -> tuple[Color, Color]:
    assert style.color is not None
    assert style.bgcolor is not None
    return _color(style.color), _color(style.bgcolor)


def _text_contrast(widget: Widget) -> float:
    foreground, background = _colors(widget.rich_style)
    return _contrast(foreground, background)


def _background(widget: Widget) -> Color:
    return _colors(widget.rich_style)[1]


def _border_contrast(widget: Widget) -> float:
    """Contrast between a mounted widget's top border and its own background."""
    _, border = widget.styles.border_top
    background = widget.background_colors[1]
    return _contrast((background + border).with_alpha(1), background.with_alpha(1))


def _mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exercise: Callable[[GitPaneApp, Pilot[None]], Awaitable[None]],
    *,
    staged: list[FileEntry] | None = None,
    unstaged: list[FileEntry] | None = None,
    size: tuple[int, int] = (100, 30),
) -> None:
    monkeypatch.setattr(
        "gitpane.app.git.status",
        lambda root: RepoState(root, staged or [], unstaged or [], "main"),
    )
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])
    monkeypatch.setattr(DiffPane, "load", lambda *_: None)

    async def run() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=size) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await exercise(app, pilot)

    asyncio.run(run())


def _rows(list_view: ListView) -> list[FileItem]:
    return [item for item in list_view.children if isinstance(item, FileItem)]


ENTRIES = [FileEntry(f"file{index}.txt", Side.UNSTAGED, "M") for index in range(3)]


def test_surfaces_and_text_are_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise(app: GitPaneApp, pilot: Pilot[None]) -> None:
        surfaces = [
            app.screen,
            app.query_one("#body"),
            app.query_one("#sidebar"),
            app.query_one("#unstaged-list"),
            app.query_one("#diff-view"),
            app.query_one("#branch-status"),
            app.query_one(".panel-title-label"),
            app.query_one(".viewer-title"),
            app.query_one(Tabs),
        ]
        for widget in surfaces:
            assert _text_contrast(widget) >= TEXT_FLOOR, widget

        # Panel chrome is visually separate from the canvas it sits on.
        assert _background(app.query_one(".viewer-title")) != _background(
            app.query_one("#body")
        )
        assert _background(app.query_one("#unstaged-list")) != _background(
            app.query_one("#body")
        )

    _mount(tmp_path, monkeypatch, exercise, unstaged=ENTRIES)


def test_list_row_states_keep_a_readable_hierarchy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise(app: GitPaneApp, pilot: Pilot[None]) -> None:
        unstaged = app.query_one("#unstaged-list", ListView)
        first, second, third = _rows(unstaged)
        unstaged.index = 0
        app.set_focus(None)
        await pilot.pause()
        assert not unstaged.has_focus

        ordinary = _background(third)
        assert _text_contrast(third) >= TEXT_FLOOR

        await pilot.hover(third)
        await pilot.pause()
        assert third.has_class("-hovered")
        hovered = _background(third)
        assert _text_contrast(third) >= TEXT_FLOOR

        await pilot.hover(second)
        await pilot.pause()
        assert not third.has_class("-hovered")
        highlighted = _background(first)
        assert _text_contrast(first) >= TEXT_FLOOR

        unstaged.focus()
        await pilot.pause()
        focused = _background(first)
        assert _text_contrast(first) >= TEXT_FLOOR
        assert first.rich_style.bold or first.query_one(".file-label").rich_style.bold
        assert _border_contrast(unstaged) >= INDICATOR_FLOOR

        # Hovering the focused selection must not weaken the selection.
        await pilot.hover(first)
        await pilot.pause()
        assert first.has_class("-hovered")
        assert _background(first) == focused

        assert len({ordinary, hovered, highlighted, focused}) == 4

    _mount(tmp_path, monkeypatch, exercise, unstaged=ENTRIES)


def test_row_actions_are_readable_when_revealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise(app: GitPaneApp, pilot: Pilot[None]) -> None:
        unstaged = app.query_one("#unstaged-list", ListView)
        _, second, _ = _rows(unstaged)
        button = second.query_one(".stage-action", Button)

        await pilot.hover(second)
        await pilot.pause()
        assert second.query_one(".file-actions").display
        assert _text_contrast(button) >= TEXT_FLOOR

    _mount(tmp_path, monkeypatch, exercise, unstaged=ENTRIES)


def test_selected_text_is_readable_in_a_mounted_code_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise(app: GitPaneApp, pilot: Pilot[None]) -> None:
        view = app.query_one("#preview-view", CodeView)
        app.query_one(TabbedContent).active = "files-tab"
        await pilot.pause()
        view.set_document((Text("selected words here"),))
        await pilot.pause()
        plain = view.render_line(0)

        app.screen.selections = {view: Selection(Offset(0, 0), Offset(8, 0))}
        await pilot.pause()
        strip = view.render_line(0)

        selected = next(segment for segment in strip if segment.text.startswith("sel"))
        rest = next(segment for segment in strip if "here" in segment.text)
        assert selected.style is not None and rest.style is not None
        assert selected.style.bgcolor != rest.style.bgcolor
        assert plain.text == strip.text
        foreground = _color(selected.style.color or view.rich_style.color)
        assert _contrast(foreground, _color(selected.style.bgcolor)) >= TEXT_FLOOR

    _mount(tmp_path, monkeypatch, exercise)


def test_diff_rows_style_additions_and_removals_in_a_mounted_code_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise(app: GitPaneApp, pilot: Pilot[None]) -> None:
        view = app.query_one("#diff-view", CodeView)
        entry = FileEntry("example.txt", Side.STAGED, "M")
        rows = [
            Row(1, 1, "context", "context"),
            Row(None, 2, "added", "add"),
            Row(2, None, "removed", "remove"),
        ]
        view.set_document(render_diff_rows(entry, rows))
        await pilot.pause()

        backgrounds = []
        for y, marker in enumerate(("context", "added", "removed")):
            strip = view.render_line(y)
            assert marker in strip.text
            segment = next(segment for segment in strip if marker in segment.text)
            assert segment.style is not None
            background = _color(segment.style.bgcolor or view.rich_style.bgcolor)
            foreground = _color(segment.style.color or view.rich_style.color)
            assert _contrast(foreground, background) >= TEXT_FLOOR
            backgrounds.append(background)

        context, added, removed = backgrounds
        assert len({context, added, removed}) == 3
        assert view.render_line(1).text.startswith("+")
        assert view.render_line(2).text.startswith("-")

    _mount(tmp_path, monkeypatch, exercise)


def test_scrollbars_are_distinguishable_from_the_code_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise(app: GitPaneApp, pilot: Pilot[None]) -> None:
        view = app.query_one("#diff-view", CodeView)
        view.set_document(tuple(Text("x" * 300) for _ in range(100)))
        await pilot.pause()

        for scrollbar in (view.vertical_scrollbar, view.horizontal_scrollbar):
            assert scrollbar.display
        # Derive the pair exactly as ScrollBar.render does from the view's styles.
        track = view.styles.scrollbar_background
        if track.a < 1:
            track = view.background_colors[0] + track
        thumb = track + view.styles.scrollbar_color
        assert _contrast(thumb, track) >= INDICATOR_FLOOR

    _mount(tmp_path, monkeypatch, exercise)


def test_long_status_path_occupies_one_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise(app: GitPaneApp, pilot: Pilot[None]) -> None:
        unstaged = app.query_one("#unstaged-list", ListView)
        long, short = _rows(unstaged)

        assert unstaged.size.width < len(LONG_PATH)
        assert long.region.height == 1
        assert long.query_one(".file-label").region.height == 1
        assert short.region.y == long.region.y + 1

    _mount(
        tmp_path,
        monkeypatch,
        exercise,
        unstaged=[
            FileEntry(LONG_PATH, Side.UNSTAGED, "M"),
            FileEntry("short.txt", Side.UNSTAGED, "M"),
        ],
    )


def test_long_diff_title_keeps_navigation_visible_and_right_aligned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise(app: GitPaneApp, pilot: Pilot[None]) -> None:
        unstaged = app.query_one("#unstaged-list", ListView)
        unstaged.focus()
        await pilot.press("enter")
        await pilot.pause()
        app.diff_pane.apply(
            DiffView(tuple(Text(f"line {index}") for index in range(20)), (2, 10)),
            app.diff_pane.request_id,
        )
        await pilot.pause()

        title = app.query_one("#diff-title", Static)
        assert str(title.content) == LONG_PATH
        bar = app.query_one(".viewer-title")
        actions = app.query_one(".diff-actions")
        previous = app.query_one("#previous-change", Button)
        following = app.query_one("#next-change", Button)

        assert title.region.height == 1
        assert title.region.width < len(LONG_PATH)
        assert title.region.right <= actions.region.x
        assert bar.region.height == 1
        for button in (previous, following):
            assert button.region.width > 0
            assert bar.region.contains_region(button.region)
        assert previous.region.right <= following.region.x
        # Right aligned: only the bar's horizontal padding follows the buttons.
        assert bar.region.right - following.region.right == bar.styles.padding.right

    _mount(
        tmp_path,
        monkeypatch,
        exercise,
        unstaged=[FileEntry(LONG_PATH, Side.UNSTAGED, "M")],
    )


def test_resizing_keeps_usable_panes_and_scrolling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise(app: GitPaneApp, pilot: Pilot[None]) -> None:
        sidebar = app.query_one("#sidebar")
        pane = app.query_one("#diff-pane")
        view = app.query_one("#diff-view", CodeView)
        view.set_document(tuple(Text(f"{index} " + "x" * 200) for index in range(100)))
        await pilot.pause()

        for width, height in ((140, 40), (80, 24), (60, 20)):
            await pilot.resize_terminal(width, height)
            await pilot.pause()
            assert sidebar.region.width >= 15
            assert pane.region.width >= 10
            assert sidebar.region.width + pane.region.width <= width
            assert view.region.height > 0
            assert view.max_scroll_y > 0
            assert view.max_scroll_x > 0
            assert view.vertical_scrollbar.display
            assert view.horizontal_scrollbar.display
            for list_view in app.query(ListView):
                assert list_view.region.height >= 3

        await pilot.press("w")
        await pilot.pause()
        assert view.has_class("wrapped")
        assert view.max_scroll_x == 0
        assert view.max_scroll_y > 0
        assert not view.horizontal_scrollbar.display
        assert view.virtual_size.width <= view.scrollable_content_region.width

        await pilot.resize_terminal(140, 40)
        await pilot.pause()
        assert view.max_scroll_x == 0
        assert view.max_scroll_y > 0

    _mount(tmp_path, monkeypatch, exercise, unstaged=ENTRIES)


def test_file_viewer_sidebar_is_resizable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise(app: GitPaneApp, pilot: Pilot[None]) -> None:
        app.query_one(TabbedContent).active = "files-tab"
        await pilot.pause()

        tree = app.query_one("#files-tree")
        pane = app.query_one("#preview-pane")
        splitter = app.file_browser.query_one(VerticalSplitter)
        initial = (tree.region.width, pane.region.width)

        await pilot.mouse_down(splitter)
        await pilot.hover(splitter, offset=(5, 0))
        await pilot.mouse_up(splitter, offset=(5, 0))
        await pilot.pause()

        assert tree.region.width > initial[0]
        assert pane.region.width < initial[1]
        assert tree.region.width + pane.region.width == sum(initial)

    _mount(tmp_path, monkeypatch, exercise)
