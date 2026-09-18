import asyncio
import functools
import os
import stat
import subprocess
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
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    ListItem,
    ListView,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)
from textual.widgets.tree import TreeNode

from gitpane import diff, git, icons
from gitpane.diff import Row
from gitpane.model import Commit, CommitFile, FileEntry, RepoState, Side
from gitpane.widgets import CodeScroll, CodeView, HorizontalSplitter, VerticalSplitter
from gitpane.widgets import JumpScrollBar as _JumpScrollBar
from gitpane.widgets import scrollbar_click_target as _scrollbar_click_target

JumpScrollBar = _JumpScrollBar
scrollbar_click_target = _scrollbar_click_target

DiffEntry = FileEntry | CommitFile


def format_file_label(entry: FileEntry, *, checked: bool = False) -> str:
    """Return the plain-text label for a status entry."""
    if entry.unsupported_reason is not None:
        return f"[!] {entry.status} {entry.path} - {entry.unsupported_reason}"
    mark = "x" if checked else " "
    return f"[{mark}] {entry.status} {entry.path}"


def format_commit_label(commit: Commit) -> Text:
    """Return a commit subject with gitmoji expanded and its hash last."""
    subject = emoji.emojize(commit.subject, language="alias")
    label = Text(f"{subject} ")
    label.append(commit.short_hash, style="dim")
    return label


@dataclass(frozen=True)
class DiffView:
    """A prepared, ready-to-render diff for one file entry."""

    lines: tuple[Text, ...]
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
    lines = render_diff_rows(entry, rows)
    first_change = diff.first_change_index(rows)
    return DiffView(lines, first_change)


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


def discard_files(root: Path, entries: Sequence[FileEntry]) -> None:
    """Discard tracked changes and remove untracked entries."""
    tracked = [entry.path for entry in entries if entry.status != "?"]
    untracked = [entry.path for entry in entries if entry.status == "?"]
    if tracked:
        git.restore(root, *tracked)
    if untracked:
        git.clean(root, *untracked)


def reconstruct_new_source(rows: Sequence[Row]) -> str:
    """Reconstruct the new side of a diff from its non-removal rows."""
    return "\n".join(row.text for row in rows if row.kind != "remove")


def lexer_for_entry(entry: DiffEntry, source: str) -> str:
    """Select Rich's lexer for an entry and its reconstructed source."""
    return Syntax.guess_lexer(entry.path, source)


def highlight_new_lines(entry: DiffEntry, rows: Sequence[Row]) -> list[Text]:
    """Highlight the reconstructed new side as individual Rich text lines."""
    new_rows = [row for row in rows if row.new_no is not None]
    if not new_rows:
        return []

    source = reconstruct_new_source(new_rows)
    syntax = Syntax(source, lexer_for_entry(entry, source))
    return syntax.highlight(source).split("\n", allow_blank=True)[: len(new_rows)]


def is_prefix_offset(offset: int) -> bool:
    """Return whether an item-local offset is within the toggle prefix."""
    return 0 <= offset <= 2


def render_diff_rows(entry: DiffEntry, rows: list[Row]) -> tuple[Text, ...]:
    """Render parsed diff rows as independently displayable Rich text lines."""
    highlighted_lines = highlight_new_lines(entry, rows)
    styles = {
        "add": Style(bgcolor="#142b1d"),
        "remove": Style(bgcolor="#351b20"),
    }
    new_side_index = 0
    lines: list[Text] = []

    for row in rows:
        line = Text()
        marker = {"add": "+", "remove": "-"}.get(row.kind, " ")
        old_no = "" if row.old_no is None else str(row.old_no)
        new_no = "" if row.new_no is None else str(row.new_no)
        line.append(f"{marker} {old_no:>4} {new_no:>4} ")
        if row.new_no is None:
            line.append(row.text)
        else:
            line.append_text(highlighted_lines[new_side_index])
            new_side_index += 1
        if style := styles.get(row.kind):
            line.stylize(style, 0, len(line))
        lines.append(line)

    return tuple(lines)


def join_diff_lines(lines: Sequence[Text]) -> Text:
    """Join prepared diff lines for the temporary Static display fallback."""
    text = Text()
    for index, line in enumerate(lines):
        if index:
            text.append("\n")
        text.append_text(line)
    return text


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
            ),
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
        super().__init__(
            label,
            Horizontal(*buttons, classes="file-actions"),
        )

    def toggle_checked(self) -> None:
        """Toggle this item for a later bulk action."""
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
            return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Translate a compact row button into a file action."""
        if event.button.name is not None:
            self.post_message(self.ActionRequested(self.entry, event.button.name))


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
        self.status_request_id = 0
        self.history_request_id = 0
        self.files_request_id = 0
        self.commit_files_request_id = 0
        self.preview_request_id = 0
        self.mutation_lock = asyncio.Lock()
        self.status_apply_lock = asyncio.Lock()
        self.history_lock = asyncio.Lock()
        self.files_lock = asyncio.Lock()
        self.diff_wrapped = False
        self.diff_view: DiffView | None = None
        self.preview_wrapped = False

    def compose(self) -> ComposeResult:
        commit_tree: Tree[Commit | CommitFile] = Tree("", id="commit-tree")
        commit_tree.show_root = False
        files_tree: Tree[Path] = Tree(
            icons.folder_label(str(self.cwd), expanded=True),
            self.cwd,
            id="files-tree",
        )
        files_tree.guide_depth = 3
        with TabbedContent(id="main-tabs"):
            with TabPane("Changes", id="changes-tab"):
                yield Horizontal(
                    Vertical(
                        Vertical(
                            Horizontal(
                                Static("Staged", classes="panel-title-label"),
                                Horizontal(
                                    Button(
                                        "↓",
                                        id="unstage-selected",
                                        classes="header-action",
                                        disabled=True,
                                        tooltip="Unstage Selected Changes",
                                        compact=True,
                                        flat=True,
                                    ),
                                    classes="header-actions",
                                    id="staged-actions",
                                ),
                                classes="panel-title",
                            ),
                            ListView(id="staged-list"),
                            id="staged-section",
                            classes="sidebar-section",
                        ),
                        HorizontalSplitter(),
                        Vertical(
                            Horizontal(
                                Static("Unstaged", classes="panel-title-label"),
                                Horizontal(
                                    Button(
                                        "↑",
                                        id="stage-selected",
                                        classes="header-action",
                                        disabled=True,
                                        tooltip="Stage Selected Changes",
                                        compact=True,
                                        flat=True,
                                    ),
                                    Button(
                                        "↶",
                                        id="discard-selected",
                                        classes="header-action discard-action",
                                        disabled=True,
                                        tooltip="Discard Selected Changes",
                                        compact=True,
                                        flat=True,
                                    ),
                                    classes="header-actions",
                                    id="unstaged-actions",
                                ),
                                classes="panel-title",
                            ),
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
                        Static(id="diff-title", classes="viewer-title", markup=False),
                        CodeView(id="diff-view"),
                        CodeScroll(Static(id="diff"), id="diff-scroll"),
                        id="diff-pane",
                    ),
                    id="body",
                )
            with TabPane("Files", id="files-tab"):
                yield Horizontal(
                    files_tree,
                    Vertical(
                        Static(id="preview-title", classes="viewer-title", markup=False),
                        CodeScroll(Static(id="preview"), id="preview-scroll"),
                        id="preview-pane",
                    ),
                    id="files-body",
                )
        yield Static(id="branch-status", markup=False)

    def on_mount(self) -> None:
        self.refresh_status()
        self.refresh_history()
        self.refresh_files()

    def action_refresh(self) -> None:
        """Reload repository views without blocking the event thread."""
        self.refresh_status()
        self.refresh_history()
        self.refresh_files()

    async def action_toggle_file(self) -> None:
        focused = self.focused
        if not isinstance(focused, ListView):
            return
        item = focused.highlighted_child
        if not isinstance(item, FileItem):
            return
        item.toggle_checked()

    def action_toggle_wrap(self) -> None:
        """Toggle wrapping in the viewer on the active tab."""
        active_tab = self.query_one("#main-tabs", TabbedContent).active
        if active_tab == "changes-tab":
            self.diff_wrapped = not self.diff_wrapped
            self._set_diff_wrapped(self.diff_wrapped)
        elif active_tab == "files-tab":
            self.preview_wrapped = not self.preview_wrapped
            self._set_wrapped("#preview", "#preview-scroll", self.preview_wrapped)

    def _active_diff_widget(self) -> CodeView | CodeScroll:
        """Return the visible diff viewer."""
        if self.diff_wrapped:
            return self.query_one("#diff-scroll", CodeScroll)
        return self.query_one("#diff-view", CodeView)

    def _set_diff_wrapped(self, wrapped: bool) -> None:
        """Switch diff renderers while retaining relative vertical progress."""
        source = (
            self.query_one("#diff-view", CodeView)
            if wrapped
            else self.query_one("#diff-scroll", CodeScroll)
        )
        progress = source.scroll_y / source.max_scroll_y if source.max_scroll_y else 0
        loading = source.loading
        view = self.query_one("#diff-view", CodeView)
        scroll = self.query_one("#diff-scroll", CodeScroll)
        content = self.query_one("#diff", Static)

        if wrapped:
            if self.diff_view is not None:
                content.update(join_diff_lines(self.diff_view.lines))
            view.set_class(True, "wrapped")
            scroll.set_class(True, "wrapped")
            content.set_class(True, "wrapped")
            scroll.scroll_to(0, 0, animate=False)
            destination: CodeView | CodeScroll = scroll
        else:
            if self.diff_view is not None:
                view.set_document(self.diff_view.lines)
            else:
                view.set_document(())
            content.update("")
            view.set_class(False, "wrapped")
            scroll.set_class(False, "wrapped")
            content.set_class(False, "wrapped")
            destination = view

        source.loading = False
        destination.loading = loading
        self.call_after_refresh(
            self._restore_diff_scroll_progress, destination, progress
        )

    def _restore_diff_scroll_progress(
        self, viewer: CodeView | CodeScroll, progress: float
    ) -> None:
        """Restore vertical progress after a diff renderer has laid out."""
        viewer.scroll_to(None, progress * viewer.max_scroll_y, animate=False)

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

    def refresh_status(self) -> None:
        """Request a working-tree status refresh."""
        token = self._start_status_refresh()
        self.load_status(token)

    def _start_status_refresh(self) -> int:
        """Set status loading state and return a new request token."""
        self.status_request_id += 1
        self.request_id += 1
        self.query_one("#staged-list", ListView).loading = True
        self.query_one("#unstaged-list", ListView).loading = True
        return self.status_request_id

    @work(group="status")
    async def load_status(self, token: int) -> None:
        """Load repository status without blocking the event thread."""
        try:
            async with self.mutation_lock:
                if not is_current_request(token, self.status_request_id):
                    return
                state = await asyncio.to_thread(git.status, self.root)
        except (subprocess.SubprocessError, OSError) as error:
            self.apply_status_error(error, token)
            return
        await self.apply_status(state, token)

    def apply_status_error(
        self, error: subprocess.SubprocessError | OSError, token: int
    ) -> None:
        """Report a status failure if it belongs to the newest request."""
        if not is_current_request(token, self.status_request_id):
            return
        self.query_one("#staged-list", ListView).loading = False
        self.query_one("#unstaged-list", ListView).loading = False
        self.query_one("#diff-view", CodeView).loading = False
        self.query_one("#diff-scroll", CodeScroll).loading = False
        self._show_git_error("refresh status", error)

    async def apply_status(self, state: RepoState, token: int) -> None:
        """Apply status data on the event thread if it is still current."""
        async with self.status_apply_lock:
            if not is_current_request(token, self.status_request_id):
                return
            self.request_id += 1
            staged_list = self.query_one("#staged-list", ListView)
            unstaged_list = self.query_one("#unstaged-list", ListView)

            await staged_list.clear()
            await unstaged_list.clear()
            await staged_list.extend(FileItem(entry) for entry in state.staged)
            await unstaged_list.extend(FileItem(entry) for entry in state.unstaged)
            staged_list.loading = False
            unstaged_list.loading = False
            self._update_bulk_actions()

            self.selection = None
            self.query_one("#branch-status", Static).update(f"Branch: {state.branch}")
            self.query_one("#diff-title", Static).update("")
            self._clear_diff()

            if state.staged:
                staged_list.index = 0
                staged_list.focus()
            elif state.unstaged:
                unstaged_list.index = 0
                unstaged_list.focus()

    def refresh_history(self) -> None:
        """Request the latest commits on the current branch."""
        self.history_request_id += 1
        self.commit_files_request_id += 1
        self.query_one("#commit-tree", Tree).loading = True
        self.load_history(self.history_request_id)

    @work(group="history")
    async def load_history(self, token: int) -> None:
        """Load commit history without blocking the event thread."""
        try:
            async with self.history_lock:
                if not is_current_request(token, self.history_request_id):
                    return
                commits = await asyncio.to_thread(git.commits, self.root)
        except (subprocess.SubprocessError, OSError) as error:
            self.apply_history_error(error, token)
            return
        self.apply_history(commits, token)

    def apply_history_error(
        self, error: subprocess.SubprocessError | OSError, token: int
    ) -> None:
        """Report a history failure if it belongs to the newest request."""
        if not is_current_request(token, self.history_request_id):
            return
        self.query_one("#commit-tree", Tree).loading = False
        self._show_git_error("refresh history", error)

    def apply_history(self, commits: list[Commit], token: int) -> None:
        """Apply commit history if it belongs to the newest request."""
        if not is_current_request(token, self.history_request_id):
            return
        self.commit_files_request_id += 1
        tree = self.query_one("#commit-tree", Tree)
        tree.clear()
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
        """Request a file-tree refresh rooted at the launch directory."""
        self.files_request_id += 1
        self.preview_request_id += 1
        tree = self.query_one("#files-tree", Tree)
        tree.loading = True
        self.load_files(self.files_request_id)

    @work(group="files")
    async def load_files(self, token: int) -> None:
        """Discover repository files without blocking the event thread."""
        try:
            async with self.files_lock:
                if not is_current_request(token, self.files_request_id):
                    return
                files = [
                    Path(relative)
                    for relative in await asyncio.to_thread(git.files, self.cwd)
                ]
        except (subprocess.SubprocessError, OSError) as error:
            self.apply_files_error(error, token)
            return
        self.apply_files(files, token)

    def apply_files_error(
        self, error: subprocess.SubprocessError | OSError, token: int
    ) -> None:
        """Report file discovery failure for the newest request."""
        if not is_current_request(token, self.files_request_id):
            return
        self.query_one("#files-tree", Tree).loading = False
        self.query_one("#preview-scroll", VerticalScroll).loading = False
        self._show_git_error("refresh files", error)

    def apply_files(self, files: list[Path], token: int) -> None:
        """Apply discovered files if they belong to the newest request."""
        if not is_current_request(token, self.files_request_id):
            return
        self.preview_request_id += 1
        tree = self.query_one("#files-tree", Tree)
        tree.clear()
        tree.root.set_label(icons.folder_label(str(self.cwd), expanded=True))
        tree.root.expand()
        nodes: dict[tuple[str, ...], TreeNode[Path]] = {(): tree.root}
        for path in files:
            parts = path.parts
            parent_parts: tuple[str, ...] = ()
            for part in parts[:-1]:
                branch_parts = (*parent_parts, part)
                if branch_parts not in nodes:
                    directory = self.cwd.joinpath(*branch_parts)
                    nodes[branch_parts] = nodes[parent_parts].add(
                        icons.folder_label(part, expanded=False), directory
                    )
                parent_parts = branch_parts
        for path in files:
            parts = path.parts
            parent_parts = parts[:-1]
            nodes[parent_parts].add_leaf(
                icons.file_label(parts[-1]), self.cwd / path
            )

        preview_scroll = self.query_one("#preview-scroll", VerticalScroll)
        tree.loading = False
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
        if isinstance(entry, FileEntry) and entry.unsupported_reason is not None:
            self.apply_diff_view(
                DiffView((Text(entry.unsupported_reason),), None), self.request_id
            )
            return
        self._active_diff_widget().loading = True
        self.load_diff(entry, self.request_id)

    @work(thread=True, exclusive=True, group="diff")
    def load_diff(self, entry: DiffEntry, token: int) -> None:
        """Load a diff on a thread worker and hand the result to the app."""
        try:
            view = load_diff_view(self.root, entry)
        except (subprocess.SubprocessError, OSError) as error:
            self.call_from_thread(self.apply_diff_error, error, token)
            return
        self.call_from_thread(self.apply_diff_view, view, token)

    def apply_diff_error(
        self, error: subprocess.SubprocessError | OSError, token: int
    ) -> None:
        """Stop the current diff loader and report its Git failure."""
        if not is_current_request(token, self.request_id):
            return
        self.query_one("#diff-view", CodeView).loading = False
        self.query_one("#diff-scroll", CodeScroll).loading = False
        self._show_git_error("load diff", error)

    def apply_diff_view(self, view: DiffView, token: int) -> None:
        """Apply a loaded diff view if it is still the current request."""
        if not is_current_request(token, self.request_id):
            return

        self.diff_view = view
        viewer = self._active_diff_widget()
        if self.diff_wrapped:
            self.query_one("#diff", Static).update(join_diff_lines(view.lines))
        else:
            self.query_one("#diff-view", CodeView).set_document(view.lines)
        self.query_one("#diff-view", CodeView).loading = False
        self.query_one("#diff-scroll", CodeScroll).loading = False
        viewer.scroll_to(0, 0, animate=False)
        if view.first_change is not None:
            self.call_after_refresh(
                viewer.scroll_to, 0, view.first_change, animate=False
            )

    def _clear_diff(self) -> None:
        """Clear both diff renderers and discard the accepted document."""
        self.diff_view = None
        view = self.query_one("#diff-view", CodeView)
        scroll = self.query_one("#diff-scroll", CodeScroll)
        view.set_document(())
        self.query_one("#diff", Static).update("")
        view.loading = False
        scroll.loading = False
        view.scroll_to(0, 0, animate=False)
        scroll.scroll_to(0, 0, animate=False)

    def on_tree_node_selected(self, event: Tree.NodeSelected[object]) -> None:
        """Handle commit expansion, historical diffs, and file previews."""
        data = event.node.data
        if event.control.id == "files-tree":
            if event.node.allow_expand or not isinstance(data, Path):
                return
            self.preview_request_id += 1
            self.query_one("#preview-title", Static).update(
                str(data.relative_to(self.root))
            )
            preview_scroll = self.query_one("#preview-scroll", VerticalScroll)
            preview_scroll.loading = True
            self.load_preview(data, self.preview_request_id)
            return
        if isinstance(data, Commit):
            return
        if isinstance(data, CommitFile):
            self.request_diff(data)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[object]) -> None:
        """Load a commit's files when either its arrow or label expands it."""
        if event.control.id == "files-tree":
            path = event.node.data
            if isinstance(path, Path):
                name = str(self.cwd) if event.node is event.control.root else path.name
                event.node.set_label(icons.folder_label(name, expanded=True))
            return
        commit = event.node.data
        if not isinstance(commit, Commit) or event.node.children:
            return
        self.commit_files_request_id += 1
        self.query_one("#commit-tree", Tree).loading = True
        self.load_commit_files(commit, event.node, self.commit_files_request_id)

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[object]) -> None:
        """Show a closed icon when a filesystem directory is collapsed."""
        if event.control.id != "files-tree":
            return
        path = event.node.data
        if isinstance(path, Path):
            name = str(self.cwd) if event.node is event.control.root else path.name
            event.node.set_label(icons.folder_label(name, expanded=False))

    @work(thread=True, exclusive=True, group="commit-files")
    def load_commit_files(
        self, commit: Commit, node: TreeNode[object], token: int
    ) -> None:
        """Load one commit's changed files on a thread worker."""
        try:
            entries = git.commit_files(self.root, commit)
        except (subprocess.SubprocessError, OSError) as error:
            self.call_from_thread(self.apply_commit_files_error, error, token)
            return
        self.call_from_thread(self.apply_commit_files, entries, node, token)

    def apply_commit_files_error(
        self, error: subprocess.SubprocessError | OSError, token: int
    ) -> None:
        """Stop the current history loader and report its Git failure."""
        if not is_current_request(token, self.commit_files_request_id):
            return
        self.query_one("#commit-tree", Tree).loading = False
        self._show_git_error("load commit files", error)

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

    def on_file_item_selection_changed(self, _: FileItem.SelectionChanged) -> None:
        self._update_bulk_actions()

    def on_file_item_action_requested(self, event: FileItem.ActionRequested) -> None:
        if event.action == "discard":
            self.request_discard([event.entry])
        else:
            self.apply_entries(event.action, [event.entry])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle bulk actions in staged and unstaged section headers."""
        if event.button.id == "stage-selected":
            self.apply_entries("stage", self._checked_entries("#unstaged-list"))
        elif event.button.id == "unstage-selected":
            self.apply_entries("unstage", self._checked_entries("#staged-list"))
        elif event.button.id == "discard-selected":
            self.request_discard(self._checked_entries("#unstaged-list"))

    def _checked_entries(self, selector: str) -> list[FileEntry]:
        """Return checked entries from a status list."""
        return [
            item.entry
            for item in self.query_one(selector, ListView).children
            if isinstance(item, FileItem) and item.checked
        ]

    def _update_bulk_actions(self) -> None:
        """Enable and reveal section actions when files are checked."""
        staged = bool(self._checked_entries("#staged-list"))
        unstaged = bool(self._checked_entries("#unstaged-list"))
        self.query_one("#staged-actions").set_class(staged, "has-selection")
        self.query_one("#unstaged-actions").set_class(unstaged, "has-selection")
        self.query_one("#unstage-selected", Button).disabled = not staged
        self.query_one("#stage-selected", Button).disabled = not unstaged
        self.query_one("#discard-selected", Button).disabled = not unstaged

    def apply_entries(self, action: str, entries: Sequence[FileEntry]) -> None:
        """Queue a stage or unstage action for one or more entries."""
        entries = [entry for entry in entries if entry.unsupported_reason is None]
        if not entries:
            return
        self.mutate_entries(action, tuple(entries))

    @work(group="mutations")
    async def mutate_entries(
        self, action: str, entries: tuple[FileEntry, ...]
    ) -> None:
        """Run one mutation at a time without blocking the event thread."""
        paths = [entry.path for entry in entries]
        async with self.mutation_lock:
            try:
                if action == "stage":
                    await asyncio.to_thread(git.stage, self.root, *paths)
                elif action == "unstage":
                    await asyncio.to_thread(git.unstage, self.root, *paths)
                elif action == "discard":
                    await asyncio.to_thread(discard_files, self.root, entries)
                else:
                    return
            except (subprocess.SubprocessError, OSError) as error:
                self._show_git_error(
                    "discard changes" if action == "discard" else action, error
                )
            token = self._start_status_refresh()
            try:
                state = await asyncio.to_thread(git.status, self.root)
            except (subprocess.SubprocessError, OSError) as error:
                self.apply_status_error(error, token)
                return
            await self.apply_status(state, token)

    def request_discard(self, entries: Sequence[FileEntry]) -> None:
        """Ask for confirmation before discarding entries."""
        entries = [entry for entry in entries if entry.unsupported_reason is None]
        if not entries:
            return
        selected = tuple(entries)

        def finish(confirmed: bool | None) -> None:
            if confirmed:
                self.mutate_entries("discard", selected)

        self.push_screen(DiscardScreen(selected), finish)

    def _show_git_error(
        self, action: str, error: subprocess.SubprocessError | OSError
    ) -> None:
        """Display a Git failure without terminating the application."""
        self.notify(
            git.error_message(error),
            title=f"Could not {action}",
            severity="error",
        )

def main() -> None:
    """Run GitPane for the current repository."""
    cwd = Path.cwd()
    GitPaneApp(git.repo_root(cwd), cwd).run()


if __name__ == "__main__":
    main()
