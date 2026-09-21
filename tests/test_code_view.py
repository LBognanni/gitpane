import asyncio

import pytest
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.geometry import Offset, Size
from textual.selection import Selection
from textual.strip import Strip

from gitpane.widgets import CodeView, scrollbar_click_target


class CodeViewApp(App[None]):
    def compose(self) -> ComposeResult:
        yield CodeView(id="code")


def visible_text(view: CodeView) -> str:
    return "\n".join(view.render_line(y).text for y in range(view.size.height))


def test_set_document_displays_content_and_extent() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(6, 2)) as pilot:
            view = app.query_one(CodeView)
            view.set_document((Text("x\t界"), Text("longest"), Text("third")))
            await pilot.pause()

            assert view.virtual_size == Size(10, 3)
            region = view.scrollable_content_region
            assert view.max_scroll_x == 10 - region.width
            assert view.max_scroll_y == 3 - region.height
            assert visible_text(view).splitlines()[0].startswith("x   ")
            assert view.scroll_offset == (0, 0)

    asyncio.run(exercise())


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

            view.scroll_to(x=2, animate=False)
            await pilot.pause()
            segments = list(view.render_line(0))
            assert segments[0].style is not None
            assert segments[0].style.meta["offset"] == (1, 0)

    asyncio.run(exercise())


def test_repaint_work_is_bounded_by_viewport_not_document_length() -> None:
    class CountingCodeView(CodeView):
        rendered_rows = 0

        def render_line(self, y: int) -> Strip:
            self.rendered_rows += 1
            return super().render_line(y)

    class CountingApp(App[None]):
        def compose(self) -> ComposeResult:
            yield CountingCodeView()

    async def rendered_rows_for(line_count: int) -> tuple[int, int, str]:
        app = CountingApp()
        async with app.run_test(size=(20, 4)) as pilot:
            view = app.query_one(CountingCodeView)
            await pilot.pause()
            view.rendered_rows = 0
            view.set_document(tuple(Text(str(index)) for index in range(line_count)))
            await pilot.pause()
            return view.rendered_rows, view.size.height, view.render_line(0).text

    async def exercise() -> None:
        small, height, _ = await rendered_rows_for(10)
        large, large_height, first_row = await rendered_rows_for(10_000)

        assert large_height == height
        assert first_row.startswith("0")
        assert 0 < small
        assert 0 < large <= max(small, height) * 2

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
            assert visible_text(view) == "\n".join(["y" * 8] * 3)

    asyncio.run(exercise())


def test_equal_document_replacement_resets_viewport() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(8, 3)) as pilot:
            view = app.query_one(CodeView)

            def document() -> tuple[Text, ...]:
                return tuple(Text(f"{row:03}" + "x" * 40) for row in range(100))

            view.set_document(document())
            await pilot.pause()
            view.scroll_to(20, 50, animate=False)
            await pilot.pause()
            assert visible_text(view) == "\n".join(["x" * 8] * 3)

            view.set_document(document())
            await pilot.pause()

            assert view.scroll_offset == (0, 0)
            assert view.max_scroll_y == 100 - view.scrollable_content_region.height
            assert visible_text(view).splitlines() == [
                "000xxxxx",
                "001xxxxx",
                "002xxxxx",
            ]

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


def test_page_keys_move_the_viewport_immediately() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(8, 4)) as pilot:
            view = app.query_one(CodeView)
            view.set_document(tuple(Text(f"{row:03}") for row in range(30)))
            await pilot.pause()
            view.focus()
            page_height = view.scrollable_content_region.height

            await pilot.press("pagedown")
            assert view.scroll_y == page_height
            assert view.render_line(0).text.rstrip() == f"{page_height:03}"

            await pilot.press("pageup")
            assert view.scroll_y == 0

    asyncio.run(exercise())


def test_wrapping_maps_source_rows_and_preserves_progress() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(10, 4)) as pilot:
            view = app.query_one(CodeView)
            view.set_document(tuple(Text(f"{row} " + "x" * 20) for row in range(20)))
            await pilot.pause()
            view.scroll_to(5, view.max_scroll_y / 2, animate=False)
            await pilot.pause()
            progress = view.scroll_y / view.max_scroll_y

            view.set_wrapped(True)
            await pilot.pause()

            assert view.scroll_x == 0
            assert view.source_to_visual_row(3) > 3
            assert view.scroll_y / view.max_scroll_y == pytest.approx(
                progress, abs=1 / view.max_scroll_y
            )

    asyncio.run(exercise())


def test_selection_uses_displayed_expanded_text_and_replacement_clears_it() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(20, 4)):
            view = app.query_one(CodeView)
            view.set_document((Text(" 1 a\tb"), Text(" 2 second")))
            selection = Selection(Offset(0, 0), Offset(9, 0))
            assert view.get_selection(selection) == (" 1 a    b", "\n")

            app.screen.selections = {view: selection}
            view.set_document((Text("replacement"),))

            assert app.screen.selections == {}

    asyncio.run(exercise())


def test_selection_handles_a_trailing_blank_line() -> None:
    view = CodeView()
    view.set_document((Text("first"), Text("")))

    assert view.get_selection(Selection(Offset(0, 0), Offset(0, 1))) == (
        "first\n",
        "\n",
    )
    assert view.get_selection(Selection(Offset(0, 1), Offset(0, 1))) == ("", "\n")


def test_selection_background_preserves_document_foreground() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(20, 4)):
            view = app.query_one(CodeView)
            view.set_document((Text("visible", style="red"),))
            app.screen.selections = {view: Selection(Offset(0, 0), Offset(7, 0))}

            style = next(iter(view.render_line(0))).style
            assert style is not None
            assert style.color == Style(color="red").color
            assert style.bgcolor is not None

    asyncio.run(exercise())


def test_wrapped_selection_uses_source_text_without_visual_newlines() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(7, 4)) as pilot:
            view = app.query_one(CodeView)
            view.set_document((Text("abc   def"), Text("second")))
            view.set_wrapped(True)
            await pilot.pause()

            assert view.virtual_size.height > len(view.lines)
            selection = Selection(Offset(0, 0), Offset(3, 1))
            assert view.get_selection(selection) == ("abc   def\nsec", "\n")

            first_continuation = view.source_to_visual_row(0) + 1
            strip = view.render_line(first_continuation)
            assert strip.text.startswith("def")
            first_segment = next(iter(strip))
            assert first_segment.style is not None
            assert first_segment.style.meta["offset"] == (6, 0)

    asyncio.run(exercise())


def test_wrapped_document_indents_continuations_without_a_gutter_only_row() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(9, 5)) as pilot:
            view = app.query_one(CodeView)
            view.set_document((Text(" 1 abcdefghijklmno"),), wrap_indent=3)
            view.set_wrapped(True)
            await pilot.pause()

            rendered = [
                view.render_line(y).text.rstrip()
                for y in range(view.virtual_size.height)
            ]
            assert rendered[0].startswith(" 1 abc")
            assert all(line.startswith("   ") for line in rendered[1:])
            assert all(line.strip() for line in rendered)

    asyncio.run(exercise())


def test_wrapped_resize_preserves_visible_source_and_selection() -> None:
    async def exercise() -> None:
        app = CodeViewApp()
        async with app.run_test(size=(16, 4)) as pilot:
            view = app.query_one(CodeView)
            lines = (Text("short"), Text("x" * 50), Text("target"), Text("y" * 50))
            view.set_document(lines)
            view.set_wrapped(True)
            await pilot.pause()
            view.scroll_to(y=view.source_to_visual_row(1) + 2, animate=False)
            await pilot.pause()
            selection = Selection(Offset(0, 2), Offset(3, 2))
            app.screen.selections = {view: selection}
            selected_before = view.get_selection(selection)
            top_before = view.render_line(0).text.strip()
            assert selected_before == ("tar", "\n")
            assert set(top_before) == {"x"}

            await pilot.resize_terminal(10, 4)

            top_after = view.render_line(0).text.strip()
            assert set(top_after) == set(top_before) == {"x"}
            assert len(top_after) < len(top_before)
            assert view.get_selection(selection) == selected_before
            assert app.screen.selections == {view: selection}

    asyncio.run(exercise())
