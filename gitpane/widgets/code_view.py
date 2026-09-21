from bisect import bisect_right
from collections.abc import Sequence

from rich.cells import get_character_cell_size
from rich.style import Style
from rich.text import Text
from textual import events
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.scrollbar import ScrollBar, ScrollTo
from textual.selection import Selection
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


class CodeView(ScrollView):
    """A selectable, virtual view of prepared Rich text lines."""

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
        self._expanded_lines: tuple[Text, ...] = ()
        self._visual_lines: tuple[Text, ...] = ()
        self._visual_source_rows: tuple[int, ...] = ()
        self._visual_source_offsets: tuple[int, ...] = ()
        self._visual_anchor_offsets: tuple[int, ...] = ()
        self._source_rows: tuple[int, ...] = ()
        self.wrap_indent = 0
        self.wrapped = False
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

    def _wrap_width(self) -> int:
        """Return the current width available to wrapped document rows."""
        if not self.is_attached:
            return max(1, self.size.width)
        return max(1, self.scrollable_content_region.width)

    @staticmethod
    def _character_offset(text: str, cell_offset: int) -> int:
        """Map a terminal-cell offset to a Python string offset."""
        cells = 0
        for offset, character in enumerate(text):
            width = get_character_cell_size(character)
            if cells + width > cell_offset:
                return offset
            cells += width
        return len(text)

    def _rebuild_visual_lines(self) -> None:
        """Reflow prepared lines and update the virtual document dimensions."""
        source_rows: list[int] = []
        visual_source_rows: list[int] = []
        visual_source_offsets: list[int] = []
        visual_anchor_offsets: list[int] = []
        visual_lines: list[Text] = []
        if self.wrapped:
            width = self._wrap_width()
            for source_row, line in enumerate(self._expanded_lines):
                source_rows.append(len(visual_lines))
                indent = min(self.wrap_indent, width - 1)
                prefix_offset = self._character_offset(line.plain, indent)
                prefix = line[:prefix_offset]
                body = line[prefix_offset:]
                wrapped_lines = list(
                    body.wrap(self.app.console, max(1, width - indent))
                    if self.is_attached
                    else []
                ) or [Text(style=line.style)]
                source_offset = 0
                for continuation, wrapped_line in enumerate(wrapped_lines):
                    if wrapped_line.plain:
                        source_offset = body.plain.find(
                            wrapped_line.plain, source_offset
                        )
                    anchor_offset = prefix_offset + max(0, source_offset)
                    if continuation:
                        visual_line = Text(" " * indent, style=line.style)
                        visual_line.append_text(wrapped_line)
                        visual_offset = anchor_offset - indent
                    else:
                        visual_line = prefix.copy()
                        visual_line.append_text(wrapped_line)
                        visual_offset = 0
                    visual_lines.append(visual_line)
                    visual_source_rows.append(source_row)
                    visual_source_offsets.append(visual_offset)
                    visual_anchor_offsets.append(anchor_offset)
                    source_offset = max(0, source_offset) + len(wrapped_line.plain)
            max_width = width if visual_lines else 0
        else:
            source_rows.extend(range(len(self._expanded_lines)))
            visual_lines.extend(self._expanded_lines)
            visual_source_rows.extend(range(len(self._expanded_lines)))
            visual_source_offsets.extend(0 for _ in self._expanded_lines)
            visual_anchor_offsets.extend(0 for _ in self._expanded_lines)
            max_width = max((line.cell_len for line in self._expanded_lines), default=0)
        self._visual_lines = tuple(visual_lines)
        self._visual_source_rows = tuple(visual_source_rows)
        self._visual_source_offsets = tuple(visual_source_offsets)
        self._visual_anchor_offsets = tuple(visual_anchor_offsets)
        self._source_rows = tuple(source_rows)
        self.virtual_size = Size(max_width, len(visual_lines))

    def set_wrapped(self, wrapped: bool) -> None:
        """Set wrapping while preserving relative vertical progress."""
        if wrapped == self.wrapped:
            return
        progress = self.scroll_y / self.max_scroll_y if self.max_scroll_y else 0
        self.wrapped = wrapped
        self.set_class(wrapped, "wrapped")
        self._rebuild_visual_lines()
        self.scroll_to(0, progress * self.max_scroll_y, animate=False)
        self.refresh()

    def source_to_visual_row(self, row: int) -> int:
        """Map a source document row to its first rendered visual row."""
        if not self._source_rows:
            return 0
        return self._source_rows[max(0, min(row, len(self._source_rows) - 1))]

    def set_document(self, lines: Sequence[Text], *, wrap_indent: int = 0) -> None:
        """Replace the document and reset its scroll position."""
        if self.is_attached and self in self.screen.selections:
            self.screen.clear_selection()
        self.lines = tuple(lines)
        self._expanded_lines = tuple(self._expanded_line(line) for line in self.lines)
        self.wrap_indent = max(0, wrap_indent)
        self._document_generation += 1
        self._rebuild_visual_lines()
        if self.is_attached:
            self.scroll_to(0, 0, animate=False)
        else:
            self.scroll_x = 0
            self.scroll_y = 0
        self.refresh()

    def on_resize(self, _: events.Resize) -> None:
        """Reflow wrapped rows when the viewport width changes."""
        if self.wrapped and self.lines:
            visual_row = min(int(self.scroll_y), len(self._visual_lines) - 1)
            source_row = self._visual_source_rows[visual_row]
            source_offset = self._visual_anchor_offsets[visual_row]
            self._rebuild_visual_lines()
            first_row = self._source_rows[source_row]
            next_row = (
                self._source_rows[source_row + 1]
                if source_row + 1 < len(self._source_rows)
                else len(self._visual_lines)
            )
            offsets = self._visual_anchor_offsets[first_row:next_row]
            row = first_row + max(0, bisect_right(offsets, source_offset) - 1)
            self.scroll_to(0, row, animate=False)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Return displayed text, including prefixes and expanded tabs."""
        lines = [line.plain for line in self._expanded_lines]
        if not lines:
            return "", "\n"

        start_row = selection.start.y if selection.start is not None else 0
        start_offset = selection.start.x if selection.start is not None else 0
        if start_row >= len(lines):
            return "", "\n"
        if selection.end is None or selection.end.y >= len(lines):
            end_row = len(lines) - 1
            end_offset = len(lines[end_row])
        else:
            end_row = selection.end.y
            end_offset = selection.end.x
        if start_row == end_row:
            return lines[start_row][start_offset:end_offset], "\n"
        selected = [lines[start_row][start_offset:]]
        selected.extend(lines[start_row + 1 : end_row])
        selected.append(lines[end_row][:end_offset])
        return "\n".join(selected), "\n"

    def render_line(self, y: int) -> Strip:
        """Render one visible document row, cropped to the viewport."""
        scroll_x, scroll_y = self.scroll_offset
        width = self.size.width
        row = scroll_y + y
        if row < 0 or row >= len(self._visual_lines):
            return Strip.blank(width, self.rich_style)

        line = self._visual_lines[row].copy()
        source_row = self._visual_source_rows[row]
        source_offset = self._visual_source_offsets[row]
        if (selection := self.text_selection) is not None:
            span = selection.get_span(source_row)
            if span is not None:
                start, end = span
                start = max(0, start - source_offset)
                if end != -1:
                    end = max(0, end - source_offset)
                selection_style = self.screen.get_component_rich_style(
                    "screen--selection"
                )
                line.stylize(
                    Style(bgcolor=selection_style.bgcolor),
                    start,
                    None if end == -1 else end,
                )
        strip = Strip(line.render(self.app.console), line.cell_len)
        visible_source_offset = source_offset + self._character_offset(
            line.plain, scroll_x
        )
        return strip.crop_extend(
            scroll_x, scroll_x + width, self.rich_style
        ).apply_offsets(visible_source_offset, source_row)
