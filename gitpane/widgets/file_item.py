from textual import events
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, ListItem, Static

from gitpane.model import FileEntry, Side


def format_file_label(entry: FileEntry, *, checked: bool = False) -> str:
    """Return the plain-text label for a status entry."""
    if entry.unsupported_reason is not None:
        return f"[!] {entry.status} {entry.path} - {entry.unsupported_reason}"
    mark = "x" if checked else " "
    return f"[{mark}] {entry.status} {entry.path}"


def is_prefix_offset(offset: int) -> bool:
    """Return whether an item-local offset is within the toggle prefix."""
    return 0 <= offset <= 2


class FileItem(ListItem):
    """A status entry displayed in a file list."""

    class SelectionChanged(Message):
        """Report that the item's bulk selection changed."""

    class ActionRequested(Message):
        """Request a single-file stage, unstage, or discard action."""

        def __init__(self, entry: FileEntry, action: str) -> None:
            self.entry = entry
            self.action = action
            super().__init__()

    def __init__(self, entry: FileEntry) -> None:
        self.entry = entry
        self.checked = False
        label = Static(format_file_label(entry), classes="file-label", markup=False)
        if entry.unsupported_reason is not None:
            super().__init__(label)
            return
        action = "unstage" if entry.side is Side.STAGED else "stage"
        arrow = "↓" if entry.side is Side.STAGED else "↑"
        buttons = [
            Button(
                arrow,
                classes=f"file-action {action}-action",
                name=action,
                tooltip="Unstage Changes" if action == "unstage" else "Stage Changes",
                compact=True,
                flat=True,
            )
        ]
        if entry.side is Side.UNSTAGED:
            buttons.append(
                Button(
                    "↶",
                    classes="file-action discard-action",
                    name="discard",
                    tooltip="Discard Changes",
                    compact=True,
                    flat=True,
                )
            )
        super().__init__(label, Horizontal(*buttons, classes="file-actions"))

    def toggle_checked(self) -> None:
        if self.entry.unsupported_reason is not None:
            return
        self.checked = not self.checked
        self.query_one(".file-label", Static).update(
            format_file_label(self.entry, checked=self.checked)
        )
        self.post_message(self.SelectionChanged())

    def _on_click(self, event: events.Click) -> None:  # type: ignore[override]
        if isinstance(event.widget, Button):
            event.prevent_default()
            event.stop()
            return
        offset = event.get_content_offset(self)
        if (
            self.entry.unsupported_reason is None
            and offset is not None
            and is_prefix_offset(offset.x)
        ):
            event.prevent_default()
            event.stop()
            self.toggle_checked()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.name is not None:
            self.post_message(self.ActionRequested(self.entry, event.button.name))
