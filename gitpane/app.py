from pathlib import Path
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import ListItem, ListView, Static

from gitpane import diff, git
from gitpane.diff import Row
from gitpane.model import FileEntry, Side


def format_file_label(entry: FileEntry) -> str:
    """Return the plain-text label for a status entry."""
    return f"[ ] {entry.status} {entry.path}"


def load_diff_rows(root: Path, entry: FileEntry) -> list[Row]:
    """Load and parse the diff for an entry."""
    return diff.parse(git.diff(root, entry))


def render_diff_rows(rows: list[Row]) -> Text:
    """Render parsed diff rows as one plain Rich text value."""
    text = Text()
    styles = {
        "add": Style(bgcolor="green"),
        "remove": Style(bgcolor="red"),
    }

    for index, row in enumerate(rows):
        if index:
            text.append("\n")
        marker = {"add": "+", "remove": "-"}.get(row.kind, " ")
        old_no = "" if row.old_no is None else str(row.old_no)
        new_no = "" if row.new_no is None else str(row.new_no)
        text.append(
            f"{marker} {old_no:>4} {new_no:>4} {row.text}",
            style=styles.get(row.kind),
        )

    return text


class FileItem(ListItem):
    """A status entry displayed in a file list."""

    def __init__(self, entry: FileEntry) -> None:
        self.entry = entry
        super().__init__(Static(format_file_label(entry), markup=False))


class GitPaneApp(App[None]):
    CSS_PATH = "app.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [Binding("r", "refresh", "Refresh")]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.selection: tuple[str, Side] | None = None

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Vertical(
                Static("Staged"),
                ListView(id="staged-list"),
                Static("Unstaged"),
                ListView(id="unstaged-list"),
                id="sidebar",
            ),
            VerticalScroll(Static(id="diff"), id="diff-scroll"),
            id="body",
        )

    async def on_mount(self) -> None:
        await self.refresh_status()

    async def action_refresh(self) -> None:
        await self.refresh_status()

    async def refresh_status(self) -> None:
        state = git.status(self.root)
        staged_list = self.query_one("#staged-list", ListView)
        unstaged_list = self.query_one("#unstaged-list", ListView)

        await staged_list.clear()
        await unstaged_list.clear()
        await staged_list.extend(FileItem(entry) for entry in state.staged)
        await unstaged_list.extend(FileItem(entry) for entry in state.unstaged)

        self.selection = None
        self.query_one("#diff", Static).update("")
        self.query_one("#diff-scroll", VerticalScroll).scroll_to(0, 0, animate=False)

        if state.staged:
            staged_list.index = 0
            staged_list.focus()
        elif state.unstaged:
            unstaged_list.index = 0
            unstaged_list.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Load the diff for a selected file entry."""
        if not isinstance(event.item, FileItem):
            return

        entry = event.item.entry
        self.selection = (entry.path, entry.side)
        rows = load_diff_rows(self.root, entry)
        self.query_one("#diff", Static).update(render_diff_rows(rows))

        diff_scroll = self.query_one("#diff-scroll", VerticalScroll)
        diff_scroll.scroll_to(0, 0, animate=False)
        first_change = diff.first_change_index(rows)
        if first_change is not None:
            self.call_after_refresh(
                diff_scroll.scroll_to, 0, first_change, animate=False
            )


def main() -> None:
    """Run GitPane for the current repository."""
    GitPaneApp(git.repo_root()).run()


if __name__ == "__main__":
    main()
