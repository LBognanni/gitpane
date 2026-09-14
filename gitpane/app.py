import functools
import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import emoji

os.environ.setdefault("TEXTUAL_SMOOTH_SCROLL", "0")

from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.scrollbar import ScrollBar, ScrollTo
from textual.widgets import ListItem, ListView, Static, TabbedContent, TabPane, Tree
from textual.widgets.tree import TreeNode

from gitpane import diff, git
from gitpane.diff import Row
from gitpane.model import Commit, CommitFile, FileEntry, Side
from gitpane.widgets import HorizontalSplitter, VerticalSplitter

DiffEntry = FileEntry | CommitFile


def format_file_label(entry: FileEntry) -> str:
    """Return the plain-text label for a status entry."""
    return f"[ ] {entry.status} {entry.path}"


def format_commit_label(commit: Commit) -> Text:
    """Return a commit subject with gitmoji expanded and its hash last."""
    subject = emoji.emojize(commit.subject, language="alias")
    label = Text(f"{subject} ")
    label.append(commit.short_hash, style="dim")
    return label


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
def build_diff_view(entry: DiffEntry, patch: str) -> DiffView:
    """Build the prepared diff view for an entry's patch text."""
    rows = diff.parse(patch)
    text = render_diff_rows(entry, rows)
    first_change = diff.first_change_index(rows)
    return DiffView(text, first_change)


def load_diff_view(root: Path, entry: DiffEntry) -> DiffView:
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


def lexer_for_entry(entry: DiffEntry, source: str) -> str:
    """Select Rich's lexer for an entry and its reconstructed source."""
    return Syntax.guess_lexer(entry.path, source)


def highlight_new_lines(entry: DiffEntry, rows: Sequence[Row]) -> list[Text]:
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


def scrollbar_click_target(
    y: float, height: int, virtual_size: int, window_size: int
) -> float:
    """Map a scrollbar track position to a centered document position."""
    if height <= 0:
        return 0
    target = (y + 0.5) / height * virtual_size - window_size / 2
    return max(0, min(target, virtual_size - window_size))


def render_diff_rows(entry: DiffEntry, rows: list[Row]) -> Text:
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


class GitPaneApp(App[None]):
    CSS_PATH = "app.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "refresh", "Refresh"),
        Binding("space", "toggle_file", "Toggle"),
        Binding("w", "toggle_wrap", "Wrap"),
    ]

    def __init__(self, root: Path, cwd: Path | None = None) -> None:
        super().__init__()
        self.root = root
        self.cwd = cwd or root
        self.selection: DiffEntry | None = None
        self.request_id = 0
        self.commit_files_request_id = 0
        self.preview_request_id = 0
        self.diff_wrapped = False
        self.preview_wrapped = False

    def compose(self) -> ComposeResult:
        commit_tree: Tree[Commit | CommitFile] = Tree("", id="commit-tree")
        commit_tree.show_root = False
        with TabbedContent(id="main-tabs"):
            with TabPane("Changes", id="changes-tab"):
                yield Horizontal(
                    Vertical(
                        Vertical(
                            Static("Staged", classes="panel-title"),
                            ListView(id="staged-list"),
                            id="staged-section",
                            classes="sidebar-section",
                        ),
                        HorizontalSplitter(),
                        Vertical(
                            Static("Unstaged", classes="panel-title"),
                            ListView(id="unstaged-list"),
                            id="unstaged-section",
                            classes="sidebar-section",
                        ),
                        HorizontalSplitter(),
                        Vertical(
                            Static("Commits", classes="panel-title"),
                            commit_tree,
                            id="commits-section",
                            classes="sidebar-section",
                        ),
                        id="sidebar",
                    ),
                    VerticalSplitter(),
                    Vertical(
                        Static(id="diff-title", classes="viewer-title"),
                        CodeScroll(Static(id="diff"), id="diff-scroll"),
                        id="diff-pane",
                    ),
                    id="body",
                )
            with TabPane("Files", id="files-tab"):
                yield Horizontal(
                    Tree[Path](Text(str(self.cwd)), id="files-tree"),
                    Vertical(
                        Static(id="preview-title", classes="viewer-title"),
                        CodeScroll(Static(id="preview"), id="preview-scroll"),
                        id="preview-pane",
                    ),
                    id="files-body",
                )
        yield Static(id="branch-status")

    async def on_mount(self) -> None:
        await self.refresh_status()
        self.refresh_history()
        self.refresh_files()

    async def action_refresh(self) -> None:
        await self.refresh_status()
        self.refresh_history()
        self.refresh_files()

    async def action_toggle_file(self) -> None:
        focused = self.focused
        if not isinstance(focused, ListView):
            return
        item = focused.highlighted_child
        if not isinstance(item, FileItem):
            return
        await self.toggle_entry(item.entry)

    def action_toggle_wrap(self) -> None:
        """Toggle wrapping in the viewer on the active tab."""
        active_tab = self.query_one("#main-tabs", TabbedContent).active
        if active_tab == "changes-tab":
            self.diff_wrapped = not self.diff_wrapped
            self._set_wrapped("#diff", "#diff-scroll", self.diff_wrapped)
        elif active_tab == "files-tab":
            self.preview_wrapped = not self.preview_wrapped
            self._set_wrapped("#preview", "#preview-scroll", self.preview_wrapped)

    def _set_wrapped(
        self, content_selector: str, scroll_selector: str, wrapped: bool
    ) -> None:
        content = self.query_one(content_selector, Static)
        scroll = self.query_one(scroll_selector, VerticalScroll)
        progress = scroll.scroll_y / scroll.max_scroll_y if scroll.max_scroll_y else 0

        content.set_class(wrapped, "wrapped")
        scroll.set_class(wrapped, "wrapped")
        if isinstance(content.content, Syntax):
            content.content.word_wrap = wrapped
            content.update(content.content)

        self.call_after_refresh(
            self._restore_scroll_progress, scroll, progress, wrapped
        )

    def _restore_scroll_progress(
        self, scroll: VerticalScroll, progress: float, wrapped: bool
    ) -> None:
        """Restore the relative vertical position after content reflows."""
        scroll.scroll_to(
            0 if wrapped else None,
            progress * scroll.max_scroll_y,
            animate=False,
        )

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
        self.query_one("#branch-status", Static).update(f"Branch: {state.branch}")
        self.query_one("#diff-title", Static).update("")
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

    def refresh_history(self) -> None:
        """Reload the latest commits on the current branch."""
        self.commit_files_request_id += 1
        tree = self.query_one("#commit-tree", Tree)
        tree.clear()
        commits = git.commits(self.root)
        for commit in commits:
            tree.root.add(format_commit_label(commit), commit)

        tree.loading = False
        if (
            commits
            and not self.query_one("#staged-list", ListView).children
            and not self.query_one("#unstaged-list", ListView).children
        ):
            tree.select_node(tree.root.children[0])
            tree.focus()

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
        self.query_one("#preview-title", Static).update("")
        self.query_one("#preview", Static).update("")
        preview_scroll.loading = False
        preview_scroll.scroll_to(0, 0, animate=False)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Start loading the diff for a selected file entry."""
        if not isinstance(event.item, FileItem):
            return
        self.request_diff(event.item.entry)

    def request_diff(self, entry: DiffEntry) -> None:
        """Start loading a working-tree or historical diff."""
        self.selection = entry
        self.query_one("#diff-title", Static).update(entry.path)
        self.request_id += 1
        self.query_one("#diff-scroll", VerticalScroll).loading = True
        self.load_diff(entry, self.request_id)

    @work(thread=True, exclusive=True, group="diff")
    def load_diff(self, entry: DiffEntry, token: int) -> None:
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

    def on_tree_node_selected(self, event: Tree.NodeSelected[object]) -> None:
        """Handle commit expansion, historical diffs, and file previews."""
        data = event.node.data
        if isinstance(data, Commit):
            if event.node.children:
                event.node.expand()
                return
            self.commit_files_request_id += 1
            self.query_one("#commit-tree", Tree).loading = True
            self.load_commit_files(data, event.node, self.commit_files_request_id)
            return
        if isinstance(data, CommitFile):
            self.request_diff(data)
            return
        if not isinstance(data, Path):
            return
        self.preview_request_id += 1
        self.query_one("#preview-title", Static).update(
            str(data.relative_to(self.root))
        )
        preview_scroll = self.query_one("#preview-scroll", VerticalScroll)
        preview_scroll.loading = True
        self.load_preview(data, self.preview_request_id)

    @work(thread=True, exclusive=True, group="commit-files")
    def load_commit_files(
        self, commit: Commit, node: TreeNode[object], token: int
    ) -> None:
        """Load one commit's changed files on a thread worker."""
        entries = git.commit_files(self.root, commit)
        self.call_from_thread(self.apply_commit_files, entries, node, token)

    def apply_commit_files(
        self, entries: list[CommitFile], node: TreeNode[object], token: int
    ) -> None:
        """Populate a commit node if it is still the selected request."""
        if not is_current_request(token, self.commit_files_request_id):
            return
        tree = self.query_one("#commit-tree", Tree)
        tree.loading = False
        for entry in entries:
            node.add_leaf(Text(f"{entry.status} {entry.path}"), entry)
        if not entries:
            node.add_leaf(Text("(no changed files)"))
        node.expand()

    @work(thread=True, exclusive=True, group="preview")
    def load_preview(self, path: Path, token: int) -> None:
        """Load a file preview on a thread worker."""
        view = load_preview_view(path)
        self.call_from_thread(self.apply_preview_view, view, token)

    def apply_preview_view(self, view: PreviewView, token: int) -> None:
        """Apply a preview only if it is still the newest request."""
        if not is_current_request(token, self.preview_request_id):
            return
        if isinstance(view.content, Syntax):
            view.content.word_wrap = self.preview_wrapped
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
