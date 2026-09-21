from pathlib import Path
from typing import ClassVar

from platformdirs import user_state_path
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


def claim_first_launch(marker_path: Path | None = None) -> bool:
    """Claim the first launch for this user and return whether it was claimed."""
    try:
        marker = marker_path or (
            user_state_path("gitpane", appauthor=False, ensure_exists=True)
            / "shortcuts-shown"
        )
        marker.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # A read-only home directory should not prevent the application starting.
        return True
    try:
        marker.touch(exist_ok=False)
    except FileExistsError:
        return False
    except OSError:
        return True
    return True


class ShortcutScreen(ModalScreen[None]):
    """Show the application's keyboard shortcuts."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "close", "Close"),
        ("h", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        shortcuts = """Mouse controls are supported throughout.

Navigation
  j / k       Move selection or scroll
  Enter       Open the selected item
  1 / 2       Changes / Files tab
  n / p       Next / previous diff change
  t           Jump to a file (Files tab)

File actions
  Space       Check or uncheck a file
  s           Stage or unstage the focused file
  d           Discard the focused unstaged file

Application
  r           Refresh repository views
  w           Toggle line wrapping
  h           Show or close this help
  q           Quit"""
        with Center():
            yield Vertical(
                Static("Keyboard Shortcuts", id="shortcuts-title"),
                Static(shortcuts, id="shortcuts-list", markup=False),
                Button("Close", id="close-shortcuts", variant="primary"),
                id="shortcuts-dialog",
            )

    def on_mount(self) -> None:
        self.query_one("#close-shortcuts", Button).focus()

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()
