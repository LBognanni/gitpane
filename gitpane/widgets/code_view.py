from collections.abc import Sequence

from rich.text import Text
from textual import events
from textual.containers import VerticalScroll
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.scrollbar import ScrollBar, ScrollTo
from textual.strip import Strip
from textual.widget import Widget


def scrollbar_click_target(
    y: float, height: int, virtual_size: int, window_size: int
) -> float:
    """Map a scrollbar track position to a centered document position."""
    if height <= 0:
        return 0
    if y <= 0:
        return 0
    if y >= height - 1:
        return max(0, virtual_size - window_size)
    target = (y + 0.5) / height * virtual_size - window_size / 2
    return max(0, min(target, virtual_size - window_size))


class JumpScrollBar(ScrollBar):
    """A scrollbar that jumps to clicked track positions."""

    def action_scroll_up(self) -> None:
        """Ignore the default page-up track action."""

    def action_scroll_down(self) -> None:
        """Ignore the default page-down track action."""

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        if (
            event.button == 1
            and self.vertical
            and event.style.meta.get("@mouse.down") != "grab"
        ):
            self.post_message(
                ScrollTo(
                    y=scrollbar_click_target(
                        event.pointer_y,
                        self.size.height,
                        self.window_virtual_size,
                        self.window_size,
                    ),
                    animate=False,
                )
            )
        event.stop()


class CodeScroll(VerticalScroll):
    """Code viewer scrolling without animated paging."""

    @property
    def vertical_scrollbar(self) -> ScrollBar:
        if self._vertical_scrollbar is None:
            self._vertical_scrollbar = JumpScrollBar(
                vertical=True,
                name="vertical",
                thickness=self.scrollbar_size_vertical,
            )
            self._vertical_scrollbar.display = False
            self.app._start_widget(self, self._vertical_scrollbar)
        return self._vertical_scrollbar

    def action_page_up(self) -> None:
        self.scroll_page_up(animate=False)

    def action_page_down(self) -> None:
        self.scroll_page_down(animate=False)


class CodeView(ScrollView):
    """A virtual, unwrapped view of prepared Rich text lines."""

    def __init__(
        self,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self.lines: tuple[Text, ...] = ()
        self._document_generation = 0

    @property
    def document_generation(self) -> int:
        """Return the generation of the current document."""
        return self._document_generation

    @property
    def vertical_scrollbar(self) -> ScrollBar:
        if self._vertical_scrollbar is None:
            self._vertical_scrollbar = JumpScrollBar(
                vertical=True,
                name="vertical",
                thickness=self.scrollbar_size_vertical,
            )
            self._vertical_scrollbar.display = False
            self.app._start_widget(self, self._vertical_scrollbar)
        return self._vertical_scrollbar

    def action_page_up(self) -> None:
        self.scroll_page_up(animate=False)

    def action_page_down(self) -> None:
        self.scroll_page_down(animate=False)

    @staticmethod
    def _expanded_line(line: Text) -> Text:
        """Return a line with tabs expanded for cell-based rendering."""
        expanded = line.copy()
        expanded.expand_tabs()
        return expanded

    def set_document(self, lines: Sequence[Text]) -> None:
        """Replace the document and reset its scroll position."""
        self.lines = tuple(lines)
        self._document_generation += 1
        max_width = max(
            (self._expanded_line(line).cell_len for line in self.lines), default=0
        )
        self.virtual_size = Size(max_width, len(self.lines))
        if self.is_attached:
            self.scroll_to(0, 0, animate=False)
        else:
            self.scroll_x = 0
            self.scroll_y = 0
        self.refresh()

    def render_line(self, y: int) -> Strip:
        """Render one visible document row, cropped to the viewport."""
        scroll_x, scroll_y = self.scroll_offset
        width = self.size.width
        row = scroll_y + y
        if row < 0 or row >= len(self.lines):
            return Strip.blank(width, self.rich_style)

        line = self._expanded_line(self.lines[row])
        strip = Strip(line.render(self.app.console), line.cell_len)
        return strip.crop_extend(
            scroll_x, scroll_x + width, self.rich_style
        ).apply_offsets(scroll_x, row)
