from textual import events
from textual.app import RenderResult
from textual.widget import Widget
from textual.widgets import Static


def resize_pair(first: int, second: int, delta: int, minimum: int) -> tuple[int, int]:
    """Resize adjacent panes while preserving their combined size."""
    total = first + second
    resized_first = max(minimum, min(first + delta, total - minimum))
    return resized_first, total - resized_first


class _Splitter(Static):
    """Mouse-drag divider which resizes its adjacent siblings."""

    ALLOW_SELECT = False

    def __init__(self, *, minimum: int) -> None:
        super().__init__()
        self.minimum = minimum
        self._drag_start = 0
        self._first_size = 0
        self._second_size = 0
        self._first: Widget | None = None
        self._second: Widget | None = None

    def _coordinate(self, event: events.MouseEvent) -> int:
        raise NotImplementedError

    def _axis_size(self, widget: Widget) -> int:
        raise NotImplementedError

    def _set_size(self, widget: Widget, size: int) -> None:
        raise NotImplementedError

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if self.parent is None:
            return
        siblings = list(self.parent.children)
        index = siblings.index(self)
        if index == 0 or index == len(siblings) - 1:
            return
        self._first = siblings[index - 1]
        self._second = siblings[index + 1]
        self._drag_start = self._coordinate(event)
        self._first_size = self._axis_size(self._first)
        self._second_size = self._axis_size(self._second)
        for sibling in siblings:
            if not isinstance(sibling, _Splitter):
                self._set_size(sibling, self._axis_size(sibling))
        self.capture_mouse()
        self.add_class("dragging")
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._first is None or self._second is None:
            return
        first, second = resize_pair(
            self._first_size,
            self._second_size,
            self._coordinate(event) - self._drag_start,
            self.minimum,
        )
        self._set_size(self._first, first)
        self._set_size(self._second, second)
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._first is None:
            return
        self.release_mouse()
        self.remove_class("dragging")
        self._first = None
        self._second = None
        event.stop()


class VerticalSplitter(_Splitter):
    """Divider between left and right panes."""

    def __init__(self, *, minimum: int = 15) -> None:
        super().__init__(minimum=minimum)

    def render(self) -> RenderResult:
        return "\n".join("│" for _ in range(max(1, self.size.height)))

    def _coordinate(self, event: events.MouseEvent) -> int:
        return event.screen_x

    def _axis_size(self, widget: Widget) -> int:
        return widget.outer_size.width

    def _set_size(self, widget: Widget, size: int) -> None:
        widget.styles.width = f"{size}fr"


class HorizontalSplitter(_Splitter):
    """Divider between upper and lower panes."""

    def __init__(self, *, minimum: int = 3) -> None:
        super().__init__(minimum=minimum)

    def render(self) -> RenderResult:
        return "─" * max(1, self.size.width)

    def _coordinate(self, event: events.MouseEvent) -> int:
        return event.screen_y

    def _axis_size(self, widget: Widget) -> int:
        return widget.outer_size.height

    def _set_size(self, widget: Widget, size: int) -> None:
        widget.styles.height = f"{size}fr"
