from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import ListItem, ListView, Static

from gitpane import git
from gitpane.model import FileEntry, Side


def format_file_label(entry: FileEntry) -> str:
    """Return the plain-text label for a status entry."""
    return f"[ ] {entry.status} {entry.path}"


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


def main() -> None:
    """Run GitPane for the current repository."""
    GitPaneApp(git.repo_root()).run()


if __name__ == "__main__":
    main()
