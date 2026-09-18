import asyncio

import pytest
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.geometry import Size
from textual.strip import Strip

from gitpane.widgets import CodeView, JumpScrollBar, scrollbar_click_target


class CodeViewApp(App[None]):
    def compose(self) -> ComposeResult:
        yield CodeView(id="code")


def test_set_document_sets_virtual_size_resets_scroll_and_bumps_generation() -> None:
    view = CodeView()
    lines = (Text("x\t界"), Text("longest"))

    view.set_document(lines)

    assert view.lines == lines
    assert view.virtual_size == Size(10, 2)
    assert view.scroll_offset == (0, 0)
    assert view.document_generation == 1

    view.set_document(lines)

    assert view.document_generation == 2


def test_render_line_crops_and_preserves_source_and_row_styles() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(5, 2)) as pilot:
            view = app.query_one(CodeView)
            line = Text("  1 ")
            line.append_text(Text("source", style=Style(color="blue")))
            line.stylize(Style(bgcolor="red"), 0, len(line))
            view.set_document((line,))
            await pilot.pause()

            strip = view.render_line(0)
            assert strip.text == "  1 s"
            assert [(segment.text, segment.style) for segment in strip] == [
                ("  1 ", Style(bgcolor="red", meta={"offset": (0, 0)})),
                (
                    "s",
                    Style(color="blue", bgcolor="red", meta={"offset": (4, 0)}),
                ),
            ]

            view.scroll_to(x=3, animate=False)
            await pilot.pause()
            strip = view.render_line(0)
            assert strip.text == " sour"
            assert [(segment.text, segment.style) for segment in strip] == [
                (" ", Style(bgcolor="red", meta={"offset": (3, 0)})),
                (
                    "sour",
                    Style(color="blue", bgcolor="red", meta={"offset": (4, 0)}),
                ),
            ]
            assert view.render_line(1) == Strip.blank(view.size.width, view.rich_style)

    asyncio.run(exercise())


def test_resize_terminal_preserves_virtual_size_and_updates_cropping() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(5, 2)) as pilot:
            view = app.query_one(CodeView)
            view.set_document(tuple(Text(f"{row}ABCDEFGHIJK") for row in range(4)))
            await pilot.pause()

            assert view.virtual_size == Size(12, 4)
            assert view.render_line(0).text == "0ABCD"

            await pilot.resize_terminal(8, 3)

            assert view.virtual_size == Size(12, 4)
            assert view.size == Size(8, 3)
            assert view.render_line(0).text == "0ABCDEFG"

            view.scroll_to(3, 1, animate=False)
            await pilot.pause()
            assert view.scroll_offset == (3, 1)
            assert view.render_line(0).text == "CDEFGHIJ"

    asyncio.run(exercise())


def test_empty_document_has_zero_virtual_dimensions() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(8, 3)) as pilot:
            view = app.query_one(CodeView)
            view.set_document(())
            await pilot.pause()

            assert view.virtual_size == Size(0, 0)
            assert view.scroll_offset == (0, 0)
            assert view.render_line(0) == Strip.blank(view.size.width, view.rich_style)

    asyncio.run(exercise())


def test_wide_unicode_uses_cell_width_and_crops_by_cells() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(3, 2)) as pilot:
            view = app.query_one(CodeView)
            view.set_document((Text("a界b"),))
            await pilot.pause()

            assert view.virtual_size == Size(4, 1)
            assert view.render_line(0).text == "a界"

            view.scroll_to(x=1, animate=False)
            await pilot.pause()

            assert view.scroll_x == 1
            assert view.render_line(0).text == "界b"

    asyncio.run(exercise())


def test_large_document_repaint_requests_only_visible_rows() -> None:
    class RecordingCodeView(CodeView):
        requested: list[int]

        def __init__(self) -> None:
            super().__init__()
            self.requested = []

        def render_line(self, y: int) -> Strip:
            self.requested.append(y + int(self.scroll_y))
            return super().render_line(y)

    class RecordingApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RecordingCodeView()

    async def exercise() -> None:
        app = RecordingApp()
        async with app.run_test(size=(20, 4)) as pilot:
            view = app.query_one(RecordingCodeView)
            view.set_document(tuple(Text(str(index)) for index in range(1_000)))
            await pilot.pause()

            assert view.requested
            assert len(set(view.requested)) < len(view.lines)
            assert max(view.requested) < view.size.height
            assert isinstance(view.vertical_scrollbar, JumpScrollBar)

    asyncio.run(exercise())


def test_document_replacement_renders_new_same_sized_content() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(8, 3)) as pilot:
            view = app.query_one(CodeView)
            view.set_document(tuple(Text("x" * 40) for _ in range(100)))
            await pilot.pause()
            view.scroll_to(20, 50, animate=False)
            await pilot.pause()

            view.set_document(tuple(Text("y" * 40) for _ in range(100)))
            await pilot.pause()

            assert view.virtual_size == Size(40, 100)
            visible_output = "\n".join(
                Strip.join(line).text
                for line in app.screen._compositor.render_full_update().strips
            )
            assert "y" in visible_output
            assert "x" not in visible_output

    asyncio.run(exercise())


def test_equal_document_replacement_resets_scrolling_and_bumps_generation() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(8, 3)) as pilot:
            view = app.query_one(CodeView)
            view.set_document(tuple(Text("x" * 40) for _ in range(100)))
            await pilot.pause()
            view.scroll_to(20, 50, animate=False)
            await pilot.pause()
            assert view.scroll_offset == (20, 50)

            view.set_document(tuple(Text("x" * 40) for _ in range(100)))
            await pilot.pause()

            assert view.scroll_offset == (0, 0)
            assert view.document_generation == 2

    asyncio.run(exercise())


def test_keyboard_and_scrollbar_navigation_is_bounded() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(8, 4)) as pilot:
            view = app.query_one(CodeView)
            view.set_document(tuple(Text(f"{row:03} " + "x" * 40) for row in range(30)))
            await pilot.pause()
            view.focus()

            await pilot.press("down", "right")
            assert view.scroll_offset == (1, 1)

            page_height = view.scrollable_content_region.height
            await pilot.press("pagedown")
            assert view.scroll_y == 1 + page_height

            # Exercise clamping near each boundary without traversing the document.
            view.scroll_to(y=view.max_scroll_y - 1, animate=False)
            await pilot.pause()
            for _ in range(2):
                await pilot.press("pagedown")
                assert view.scroll_y == view.max_scroll_y

            view.scroll_to(y=1, animate=False)
            await pilot.pause()
            for _ in range(2):
                await pilot.press("pageup")
                assert view.scroll_y == 0

            view.scroll_to(x=view.max_scroll_x - 1, animate=False)
            await pilot.pause()
            for _ in range(2):
                await pilot.press("right")
                assert view.scroll_x == view.max_scroll_x
                assert view.scroll_y == 0

            scrollbar = view.vertical_scrollbar
            assert await pilot.click(scrollbar, offset=(0, scrollbar.size.height - 1))
            await pilot.pause()
            assert view.scroll_y == view.max_scroll_y
            assert 0 <= view.scroll_y <= view.max_scroll_y

            assert await pilot.click(scrollbar, offset=(0, 0))
            await pilot.pause()
            assert view.scroll_y == 0
            assert 0 <= view.scroll_y <= view.max_scroll_y

    asyncio.run(exercise())


def test_scrollbar_target_handles_empty_and_short_documents() -> None:
    assert scrollbar_click_target(0, 0, 0, 0) == 0
    assert scrollbar_click_target(0, 10, 2, 5) == 0


def test_page_actions_are_unanimated(monkeypatch: pytest.MonkeyPatch) -> None:
    view = CodeView()
    calls: list[tuple[str, bool]] = []

    def page_up(*, animate: bool) -> None:
        calls.append(("up", animate))

    def page_down(*, animate: bool) -> None:
        calls.append(("down", animate))

    monkeypatch.setattr(view, "scroll_page_up", page_up)
    monkeypatch.setattr(view, "scroll_page_down", page_down)

    view.action_page_up()
    view.action_page_down()

    assert calls == [("up", False), ("down", False)]
