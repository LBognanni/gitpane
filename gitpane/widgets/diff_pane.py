import subprocess
from collections.abc import Callable
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from gitpane.diff_view import (
    DIFF_CONTEXT_LINES,
    DiffEntry,
    DiffView,
    load_diff_view,
)
from gitpane.model import FileEntry
from gitpane.widgets.code_view import CodeView

ErrorHandler = Callable[[str, subprocess.SubprocessError | OSError], None]


class DiffPane(Vertical):
    """Own the shared working-tree and history diff viewer."""

    def __init__(self, root: Path, on_error: ErrorHandler) -> None:
        super().__init__(id="diff-pane")
        self.root = root
        self.on_error = on_error
        self.selection: DiffEntry | None = None
        self.request_id = 0
        self.diff_view: DiffView | None = None
        self.change_index: int | None = None
        self.wrapped = False

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static(id="diff-title", classes="viewer-title-label", markup=False),
            Horizontal(
                Button(
                    "↑",
                    id="previous-change",
                    classes="diff-action",
                    disabled=True,
                    tooltip="Previous Change",
                    compact=True,
                    flat=True,
                ),
                Button(
                    "↓",
                    id="next-change",
                    classes="diff-action",
                    disabled=True,
                    tooltip="Next Change",
                    compact=True,
                    flat=True,
                ),
                classes="diff-actions",
            ),
            classes="viewer-title",
        )
        yield CodeView(id="diff-view")

    def request(self, entry: DiffEntry) -> None:
        self.selection = entry
        self.query_one("#diff-title", Static).update(entry.path)
        self.change_index = None
        self._update_navigation()
        self.request_id += 1
        if isinstance(entry, FileEntry) and entry.unsupported_reason is not None:
            self.apply(DiffView((Text(entry.unsupported_reason),), ()), self.request_id)
            return
        self.query_one("#diff-view", CodeView).loading = True
        self.load(entry, self.request_id)

    @work(thread=True, exclusive=True, group="diff")
    def load(self, entry: DiffEntry, token: int) -> None:
        try:
            view = load_diff_view(self.root, entry)
        except (subprocess.SubprocessError, OSError) as error:
            self.app.call_from_thread(self.apply_error, error, token)
            return
        self.app.call_from_thread(self.apply, view, token)

    def apply_error(
        self, error: subprocess.SubprocessError | OSError, token: int
    ) -> None:
        if token != self.request_id:
            return
        self.query_one("#diff-view", CodeView).loading = False
        self.on_error("load diff", error)

    def apply(self, view: DiffView, token: int) -> None:
        if token != self.request_id:
            return
        self.diff_view = view
        self.change_index = 0 if view.changes else None
        self._update_navigation()
        viewer = self.query_one("#diff-view", CodeView)
        viewer.set_document(view.lines)
        viewer.loading = False
        viewer.scroll_to(0, 0, animate=False)
        if view.first_change is not None:
            self.call_after_refresh(self._scroll_to_change, 0)

    def invalidate(self, *, clear: bool = True) -> None:
        """Invalidate pending work and optionally clear the accepted document."""
        self.request_id += 1
        if not clear:
            return
        self.selection = None
        self.query_one("#diff-title", Static).update("")
        self.diff_view = None
        self.change_index = None
        self._update_navigation()
        viewer = self.query_one("#diff-view", CodeView)
        viewer.set_document(())
        viewer.loading = False

    def toggle_wrap(self) -> None:
        self.wrapped = not self.wrapped
        self.query_one("#diff-view", CodeView).set_wrapped(self.wrapped)

    def stop_loading(self) -> None:
        self.query_one("#diff-view", CodeView).loading = False

    def navigate(self, offset: int) -> None:
        if self.diff_view is None or self.change_index is None:
            return
        target = self.change_index + offset
        if not 0 <= target < len(self.diff_view.changes):
            return
        self.change_index = target
        self._update_navigation()
        self._scroll_to_change(target)

    def _scroll_to_change(self, index: int) -> None:
        if self.diff_view is None:
            return
        row = max(0, self.diff_view.changes[index] - DIFF_CONTEXT_LINES)
        viewer = self.query_one("#diff-view", CodeView)
        viewer.scroll_to(0, viewer.source_to_visual_row(row), animate=False)

    def _update_navigation(self) -> None:
        previous = self.query_one("#previous-change", Button)
        next_change = self.query_one("#next-change", Button)
        index = self.change_index
        count = len(self.diff_view.changes) if self.diff_view is not None else 0
        previous.disabled = index is None or index == 0
        next_change.disabled = index is None or index >= count - 1

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "previous-change":
            self.navigate(-1)
        elif event.button.id == "next-change":
            self.navigate(1)
