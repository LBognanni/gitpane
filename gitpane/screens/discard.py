from collections.abc import Sequence
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Center, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from gitpane.model import FileEntry


class DiscardScreen(ModalScreen[bool]):
    """Confirm a destructive discard operation."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    def __init__(self, entries: Sequence[FileEntry]) -> None:
        super().__init__()
        self.entries = tuple(entries)

    def compose(self) -> ComposeResult:
        count = len(self.entries)
        noun = "file" if count == 1 else "files"
        message = f"Discard changes to {count} {noun}? This cannot be undone."
        if any(entry.status == "?" for entry in self.entries):
            message += " Untracked files will be permanently deleted."
        with Center():
            yield Vertical(
                Static("Discard Changes?", id="discard-title"),
                Static(message, id="discard-message"),
                Horizontal(
                    Button("Cancel", id="cancel-discard"),
                    Button("Discard", variant="error", id="confirm-discard"),
                    id="discard-buttons",
                ),
                id="discard-dialog",
            )

    def on_mount(self) -> None:
        self.query_one("#cancel-discard", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-discard")

    def action_cancel(self) -> None:
        self.dismiss(False)
