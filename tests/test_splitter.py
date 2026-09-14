import asyncio

import pytest
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from gitpane.widgets.splitter import HorizontalSplitter, VerticalSplitter, resize_pair


@pytest.mark.parametrize(
    ("first", "second", "delta", "minimum", "expected"),
    [
        (30, 70, 10, 15, (40, 60)),
        (30, 70, -100, 15, (15, 85)),
        (30, 70, 100, 15, (85, 15)),
        (3, 3, 0, 3, (3, 3)),
    ],
)
def test_resize_pair_preserves_total_and_minimums(
    first: int,
    second: int,
    delta: int,
    minimum: int,
    expected: tuple[int, int],
) -> None:
    assert resize_pair(first, second, delta, minimum) == expected


def test_vertical_splitter_resizes_adjacent_panes_with_mouse() -> None:
    class SplitterApp(App[None]):
        CSS = """
        #row { width: 40; height: 5; }
        #first { width: 15; }
        VerticalSplitter { width: 1; }
        #second { width: 1fr; }
        """

        def compose(self) -> ComposeResult:
            yield Horizontal(
                Static(id="first"),
                VerticalSplitter(minimum=5),
                Static(id="second"),
                id="row",
            )

    async def exercise() -> None:
        app = SplitterApp()
        async with app.run_test() as pilot:
            splitter = app.query_one(VerticalSplitter)
            first = app.query_one("#first", Static)
            second = app.query_one("#second", Static)
            initial = (first.outer_size.width, second.outer_size.width)

            await pilot.mouse_down(splitter)
            await pilot.hover(splitter, offset=(5, 0))
            await pilot.mouse_up(splitter, offset=(5, 0))
            await pilot.pause()

            assert splitter.allow_select is False
            assert app.screen.selections == {}
            assert first.outer_size.width > initial[0]
            assert second.outer_size.width < initial[1]
            assert first.outer_size.width + second.outer_size.width == sum(initial)

    asyncio.run(exercise())


def test_splitters_render_understated_directional_lines() -> None:
    class SplitterApp(App[None]):
        CSS = """
        #row { width: 10; height: 4; }
        VerticalSplitter { width: 1; height: 4; }
        HorizontalSplitter { width: 10; height: 1; }
        """

        def compose(self) -> ComposeResult:
            yield Horizontal(VerticalSplitter(), HorizontalSplitter(), id="row")

    async def exercise() -> None:
        app = SplitterApp()
        async with app.run_test():
            vertical = app.query_one(VerticalSplitter)
            horizontal = app.query_one(HorizontalSplitter)

            assert vertical.render() == "│\n│\n│\n│"
            assert horizontal.render() == "─" * 10

    asyncio.run(exercise())


def test_dragging_first_splitter_preserves_third_pane_weight() -> None:
    class ThreePaneApp(App[None]):
        CSS = """
        #column { width: 20; height: 20; }
        .pane { height: 1fr; }
        HorizontalSplitter { height: 1; }
        """

        def compose(self) -> ComposeResult:
            yield Vertical(
                Static(id="first", classes="pane"),
                HorizontalSplitter(),
                Static(id="second", classes="pane"),
                HorizontalSplitter(),
                Static(id="third", classes="pane"),
                id="column",
            )

    async def exercise() -> None:
        app = ThreePaneApp()
        async with app.run_test() as pilot:
            splitters = list(app.query(HorizontalSplitter))
            third = app.query_one("#third", Static)
            initial_third_height = third.outer_size.height

            await pilot.mouse_down(splitters[0])
            await pilot.hover(splitters[0], offset=(0, 2))
            await pilot.mouse_up(splitters[0], offset=(0, 2))
            await pilot.pause()

            assert third.outer_size.height == initial_third_height

    asyncio.run(exercise())
