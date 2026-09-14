import functools
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import ListItem, ListView, Static, TabbedContent, TabPane, Tree
from textual.widgets.tree import TreeNode

from gitpane import diff, git
from gitpane.diff import Row
from gitpane.model import FileEntry, Side


def format_file_label(entry: FileEntry) -> str:
    """Return the plain-text label for a status entry."""
    return f"[ ] {entry.status} {entry.path}"


@dataclass(frozen=True)
class DiffView:
    """A prepared, ready-to-render diff for one file entry."""

    text: Text
    first_change: int | None


@dataclass(frozen=True)
class PreviewView:
    """A ready-to-render file preview or friendly error message."""

    content: Syntax | Text


MAX_PREVIEW_BYTES = 1024 * 1024


@functools.lru_cache(maxsize=4)
def build_diff_view(entry: FileEntry, patch: str) -> DiffView:
    """Build the prepared diff view for an entry's patch text."""
    rows = diff.parse(patch)
    text = render_diff_rows(entry, rows)
    first_change = diff.first_change_index(rows)
    return DiffView(text, first_change)


def load_diff_view(root: Path, entry: FileEntry) -> DiffView:
    """Load the diff for an entry and return its prepared view."""
    patch = git.diff(root, entry)
    return build_diff_view(entry, patch)


def load_preview_view(path: Path) -> PreviewView:
    """Read and prepare a bounded UTF-8 text file preview."""
    try:
        file_stat = path.lstat()
        if not stat.S_ISREG(file_stat.st_mode):
            return PreviewView(Text("Only regular files can be previewed."))
        if file_stat.st_size > MAX_PREVIEW_BYTES:
            return PreviewView(Text("File is too large to preview (maximum 1 MiB)."))
        with path.open("rb") as file:
            data = file.read(MAX_PREVIEW_BYTES + 1)
    except FileNotFoundError:
        return PreviewView(Text("File is no longer available."))
    except OSError:
        return PreviewView(Text("File could not be read."))

    if len(data) > MAX_PREVIEW_BYTES:
        return PreviewView(Text("File is too large to preview (maximum 1 MiB)."))
    if b"\0" in data:
        return PreviewView(Text("Binary files cannot be previewed."))
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError:
        return PreviewView(Text("File is not valid UTF-8."))

    lexer = Syntax.guess_lexer(path.name, source)
    return PreviewView(Syntax(source, lexer, line_numbers=True, word_wrap=False))


def is_current_request(token: int, current: int) -> bool:
    """Return whether a request token still matches the current one."""
    return token == current


def toggle_file(root: Path, entry: FileEntry) -> None:
    """Stage or unstage an entry according to its side."""
    if entry.side is Side.STAGED:
        git.unstage(root, entry.path)
    else:
        git.stage(root, entry.path)


def reconstruct_new_source(rows: Sequence[Row]) -> str:
    """Reconstruct the new side of a diff from its non-removal rows."""
    return "\n".join(row.text for row in rows if row.kind != "remove")


def lexer_for_entry(entry: FileEntry, source: str) -> str:
    """Select Rich's lexer for an entry and its reconstructed source."""
    return Syntax.guess_lexer(entry.path, source)


def highlight_new_lines(entry: FileEntry, rows: Sequence[Row]) -> list[Text]:
    """Highlight the reconstructed new side as individual Rich text lines."""
    new_rows = [row for row in rows if row.kind != "remove"]
    if not new_rows:
        return []

    source = reconstruct_new_source(new_rows)
    syntax = Syntax(source, lexer_for_entry(entry, source))
    return syntax.highlight(source).split("\n", allow_blank=True)[: len(new_rows)]


def is_prefix_offset(offset: int) -> bool:
    """Return whether an item-local offset is within the toggle prefix."""
    return 0 <= offset <= 2


def render_diff_rows(entry: FileEntry, rows: list[Row]) -> Text:
    """Render parsed diff rows as one plain Rich text value."""
    text = Text()
    highlighted_lines = highlight_new_lines(entry, rows)
    styles = {
        "add": Style(bgcolor="#142b1d"),
        "remove": Style(bgcolor="#351b20"),
    }
    new_side_index = 0

    for index, row in enumerate(rows):
        if index:
            text.append("\n")
        row_start = len(text)
        marker = {"add": "+", "remove": "-"}.get(row.kind, " ")
        old_no = "" if row.old_no is None else str(row.old_no)
        new_no = "" if row.new_no is None else str(row.new_no)
        text.append(f"{marker} {old_no:>4} {new_no:>4} ")
        if row.new_no is None:
            text.append(row.text)
        else:
            text.append_text(highlighted_lines[new_side_index])
            new_side_index += 1
        if style := styles.get(row.kind):
            text.stylize(style, row_start, len(text))

    return text


class FileItem(ListItem):
    """A status entry displayed in a file list."""

    class ToggleRequested(Message):
        """Request that an entry be staged or unstaged."""

        def __init__(self, entry: FileEntry) -> None:
            self.entry = entry
            super().__init__()

    def __init__(self, entry: FileEntry) -> None:
        self.entry = entry
        super().__init__(Static(format_file_label(entry), markup=False))

    def _on_click(self, event: events.Click) -> None:  # type: ignore[override]
        offset = event.get_content_offset(self)
        if offset is not None and is_prefix_offset(offset.x):
            event.stop()
            self.post_message(self.ToggleRequested(self.entry))
            return
        self.post_message(self._ChildClicked(self))


class GitPaneApp(App[None]):
    CSS_PATH = "app.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "refresh", "Refresh"),
        Binding("space", "toggle_file", "Toggle"),
    ]

    def __init__(self, root: Path, cwd: Path | None = None) -> None:
        super().__init__()
        self.root = root
        self.cwd = cwd or root
        self.selection: tuple[str, Side] | None = None
        self.request_id = 0
        self.preview_request_id = 0

    def compose(self) -> ComposeResult:
        with TabbedContent(id="main-tabs"):
            with TabPane("Changes", id="changes-tab"):
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
            with TabPane("Files", id="files-tab"):
                yield Horizontal(
                    Tree[Path](Text(str(self.cwd)), id="files-tree"),
                    VerticalScroll(Static(id="preview"), id="preview-scroll"),
                    id="files-body",
                )

    async def on_mount(self) -> None:
        await self.refresh_status()
        self.refresh_files()

    async def action_refresh(self) -> None:
        await self.refresh_status()
        self.refresh_files()

    async def action_toggle_file(self) -> None:
        focused = self.focused
        if not isinstance(focused, ListView):
            return
        item = focused.highlighted_child
        if not isinstance(item, FileItem):
            return
        await self.toggle_entry(item.entry)

    async def refresh_status(self) -> None:
        self.request_id += 1
        state = git.status(self.root)
        staged_list = self.query_one("#staged-list", ListView)
        unstaged_list = self.query_one("#unstaged-list", ListView)

        await staged_list.clear()
        await unstaged_list.clear()
        await staged_list.extend(FileItem(entry) for entry in state.staged)
        await unstaged_list.extend(FileItem(entry) for entry in state.unstaged)

        self.selection = None
        self.query_one("#diff", Static).update("")
        diff_scroll = self.query_one("#diff-scroll", VerticalScroll)
        diff_scroll.scroll_to(0, 0, animate=False)
        diff_scroll.loading = False

        if state.staged:
            staged_list.index = 0
            staged_list.focus()
        elif state.unstaged:
            unstaged_list.index = 0
            unstaged_list.focus()

    def refresh_files(self) -> None:
        """Reload the file tree rooted at the launch directory."""
        self.preview_request_id += 1
        tree = self.query_one("#files-tree", Tree)
        tree.clear()
        tree.root.set_label(Text(str(self.cwd)))
        tree.root.expand()
        nodes: dict[tuple[str, ...], TreeNode[Path]] = {(): tree.root}
        for relative in git.files(self.cwd):
            parts = Path(relative).parts
            parent_parts: tuple[str, ...] = ()
            for part in parts[:-1]:
                branch_parts = (*parent_parts, part)
                if branch_parts not in nodes:
                    nodes[branch_parts] = nodes[parent_parts].add(Text(part))
                parent_parts = branch_parts
            nodes[parent_parts].add_leaf(Text(parts[-1]), self.cwd / relative)

        preview_scroll = self.query_one("#preview-scroll", VerticalScroll)
        self.query_one("#preview", Static).update("")
        preview_scroll.loading = False
        preview_scroll.scroll_to(0, 0, animate=False)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Start loading the diff for a selected file entry."""
        if not isinstance(event.item, FileItem):
            return

        entry = event.item.entry
        self.selection = (entry.path, entry.side)
        self.request_id += 1
        self.query_one("#diff-scroll", VerticalScroll).loading = True
        self.load_diff(entry, self.request_id)

    @work(thread=True, exclusive=True, group="diff")
    def load_diff(self, entry: FileEntry, token: int) -> None:
        """Load a diff on a thread worker and hand the result to the app."""
        view = load_diff_view(self.root, entry)
        self.call_from_thread(self.apply_diff_view, view, token)

    def apply_diff_view(self, view: DiffView, token: int) -> None:
        """Apply a loaded diff view if it is still the current request."""
        if not is_current_request(token, self.request_id):
            return

        self.query_one("#diff", Static).update(view.text)
        diff_scroll = self.query_one("#diff-scroll", VerticalScroll)
        diff_scroll.loading = False
        diff_scroll.scroll_to(0, 0, animate=False)
        if view.first_change is not None:
            self.call_after_refresh(
                diff_scroll.scroll_to, 0, view.first_change, animate=False
            )

    def on_tree_node_selected(self, event: Tree.NodeSelected[Path]) -> None:
        """Start loading the selected file on a thread worker."""
        path = event.node.data
        if path is None:
            return
        self.preview_request_id += 1
        preview_scroll = self.query_one("#preview-scroll", VerticalScroll)
        preview_scroll.loading = True
        self.load_preview(path, self.preview_request_id)

    @work(thread=True, exclusive=True, group="preview")
    def load_preview(self, path: Path, token: int) -> None:
        """Load a file preview on a thread worker."""
        view = load_preview_view(path)
        self.call_from_thread(self.apply_preview_view, view, token)

    def apply_preview_view(self, view: PreviewView, token: int) -> None:
        """Apply a preview only if it is still the newest request."""
        if not is_current_request(token, self.preview_request_id):
            return
        self.query_one("#preview", Static).update(view.content)
        preview_scroll = self.query_one("#preview-scroll", VerticalScroll)
        preview_scroll.loading = False
        preview_scroll.scroll_to(0, 0, animate=False)

    async def on_file_item_toggle_requested(
        self, event: FileItem.ToggleRequested
    ) -> None:
        await self.toggle_entry(event.entry)

    async def toggle_entry(self, entry: FileEntry) -> None:
        toggle_file(self.root, entry)
        await self.refresh_status()


def main() -> None:
    """Run GitPane for the current repository."""
    cwd = Path.cwd()
    GitPaneApp(git.repo_root(cwd), cwd).run()


if __name__ == "__main__":
    main()
