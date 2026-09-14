"""Small headless app used to exercise the production code viewer."""

from rich.syntax import Syntax
from rich.text import Text
from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.widgets import Static

from gitpane.app import CodeScroll, JumpScrollBar, scrollbar_click_target

ViewerContent = Text | Syntax


class ViewerHarness(App[None]):
    """One production ``CodeScroll`` and one ``Static``, without repository UI."""

    CSS = """
    CodeScroll {
        height: 1fr;
        overflow: scroll scroll;
    }

    #viewer-content {
        width: auto;
        text-wrap: nowrap;
    }

    CodeScroll.wrapped {
        overflow-x: hidden;
    }

    #viewer-content.wrapped {
        width: 100%;
        text-wrap: wrap;
    }
    """

    def compose(self) -> ComposeResult:
        yield CodeScroll(Static(id="viewer-content"), id="viewer-scroll")

    @property
    def content(self) -> Static:
        """Return the mounted document widget."""
        return self.query_one("#viewer-content", Static)

    @property
    def scroll(self) -> CodeScroll:
        """Return the mounted production scroll container."""
        return self.query_one("#viewer-scroll", CodeScroll)

    async def update_and_settle(
        self, pilot: Pilot[None], content: ViewerContent
    ) -> None:
        """Update the document and allow its next headless frame to paint."""
        self.content.update(content)
        await pilot.pause()

    async def settle(self, pilot: Pilot[None]) -> None:
        """Allow one frame after a viewport operation."""
        await pilot.pause()

    async def line_down(self, pilot: Pilot[None]) -> None:
        """Perform one bounded, unanimated line scroll."""
        self.scroll.scroll_relative(y=1, animate=False)
        await self.settle(pilot)

    async def page_down(self, pilot: Pilot[None]) -> None:
        """Perform the production unanimated page-down action."""
        self.scroll.action_page_down()
        await self.settle(pilot)

    async def jump_to_fraction(self, pilot: Pilot[None], fraction: float) -> None:
        """Use the production scrollbar-target mapping for a track fraction."""
        scrollbar = self.scroll.vertical_scrollbar
        assert isinstance(scrollbar, JumpScrollBar)
        target = scrollbar_click_target(
            scrollbar.size.height * fraction,
            scrollbar.size.height,
            scrollbar.window_virtual_size,
            scrollbar.window_size,
        )
        self.scroll.scroll_to(y=target, animate=False)
        await self.settle(pilot)

    async def horizontal_positive_and_reset(self, pilot: Pilot[None]) -> None:
        """Move right once, then reset left outside the timed positive operation."""
        scroll = self.scroll
        scroll.scroll_to(x=min(20, scroll.max_scroll_x), animate=False)
        await self.settle(pilot)

    async def reset_horizontal(self, pilot: Pilot[None]) -> None:
        """Return horizontal position to the origin between samples."""
        self.scroll.scroll_to(x=0, animate=False)
        await self.settle(pilot)

    async def set_wrapped(self, pilot: Pilot[None], wrapped: bool) -> None:
        """Apply the same wrapping state mutation as ``GitPaneApp._set_wrapped``."""
        content = self.content
        scroll = self.scroll
        progress = scroll.scroll_y / scroll.max_scroll_y if scroll.max_scroll_y else 0
        content.set_class(wrapped, "wrapped")
        scroll.set_class(wrapped, "wrapped")
        if isinstance(content.content, Syntax):
            content.content.word_wrap = wrapped
            content.update(content.content)
        self.call_after_refresh(self._restore_scroll_progress, progress, wrapped)
        await self.settle(pilot)

    def _restore_scroll_progress(self, progress: float, wrapped: bool) -> None:
        """Match the production relative-position restoration after reflow."""
        self.scroll.scroll_to(
            0 if wrapped else None,
            progress * self.scroll.max_scroll_y,
            animate=False,
        )
