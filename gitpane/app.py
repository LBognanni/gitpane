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
from platformdirs import user_state_path

os.environ.setdefault("TEXTUAL_SMOOTH_SCROLL", "0")

from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    ListItem,
    ListView,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from gitpane import diff, git, icons
from gitpane.diff import Row
from gitpane.model import Commit, CommitFile, FileEntry, RepoState, Side
from gitpane.widgets import CodeView, HorizontalSplitter, VerticalSplitter
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
    changes: tuple[int, ...]

    @property
    def first_change(self) -> int | None:
        return self.changes[0] if self.changes else None


@dataclass(frozen=True)
class PreviewView:
    """Prepared, ready-to-render preview lines."""

    lines: tuple[Text, ...]
    wrap_indent: int = 0


MAX_PREVIEW_BYTES = 1024 * 1024
DIFF_CONTEXT_LINES = 4
MAX_FILE_JUMP_RESULTS = 100


@functools.lru_cache(maxsize=4)
def build_diff_view(entry: DiffEntry, patch: str) -> DiffView:
    """Build the prepared diff view for an entry's patch text."""
    rows = diff.parse(patch)
    lines = render_diff_rows(entry, rows)
    return DiffView(lines, diff.change_indices(rows))


def load_diff_view(root: Path, entry: DiffEntry) -> DiffView:
    """Load the diff for an entry and return its prepared view."""
    patch = git.diff(root, entry)
    return build_diff_view(entry, patch)


def load_preview_view(path: Path) -> PreviewView:
    """Read and prepare a bounded UTF-8 text file preview."""

    def message(text: str) -> PreviewView:
        return PreviewView((Text(text),))

    try:
        file_stat = path.lstat()
        if not stat.S_ISREG(file_stat.st_mode):
            return message("Only regular files can be previewed.")
        if file_stat.st_size > MAX_PREVIEW_BYTES:
            return message("File is too large to preview (maximum 1 MiB).")
        with path.open("rb") as file:
            data = file.read(MAX_PREVIEW_BYTES + 1)
    except FileNotFoundError:
        return message("File is no longer available.")
    except OSError:
        return message("File could not be read.")

    if len(data) > MAX_PREVIEW_BYTES:
        return message("File is too large to preview (maximum 1 MiB).")
    if b"\0" in data:
        return message("Binary files cannot be previewed.")
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError:
        return message("File is not valid UTF-8.")

    source = source.replace("\r\n", "\n").replace("\r", "\n")
    lexer = Syntax.guess_lexer(path.name, source)
    syntax = Syntax(source, lexer)
    highlighted = list(syntax.highlight(source).split("\n", allow_blank=True))
    line_count = source.count("\n") + 1
    highlighted = highlighted[:line_count]
    number_width = len(str(len(highlighted)))
    lines: list[Text] = []
    for number, highlighted_line in enumerate(highlighted, 1):
        line = Text()
        line.append(f" {number:>{number_width}} ", style="dim")
        line.append_text(highlighted_line)
        lines.append(line)
    return PreviewView(tuple(lines), number_width + 2)


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


def matching_files(
    files: Sequence[tuple[Path, str]], query: str
) -> tuple[tuple[Path, ...], bool]:
    """Return bounded, case-insensitive matches from an in-memory file index."""
    if len(query) < 3:
        return (), False
    needle = query.casefold()
    matches: list[Path] = []
    for path, searchable_path in files:
        if needle in searchable_path:
            matches.append(path)
            if len(matches) > MAX_FILE_JUMP_RESULTS:
                break
    return tuple(matches[:MAX_FILE_JUMP_RESULTS]), len(matches) > MAX_FILE_JUMP_RESULTS


class FileJumpScreen(ModalScreen[Path | None]):
    """Select a repository file from an in-memory path index."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    def __init__(self, files: Sequence[tuple[Path, str]]) -> None:
        super().__init__()
        self.files = tuple(files)
        self.matches: tuple[Path, ...] = ()
        self.search_request_id = 0

    def compose(self) -> ComposeResult:
        yield Vertical(
            Input(placeholder="Jump to file", id="file-jump-input"),
            OptionList(id="file-jump-results", markup=False, compact=True),
            id="file-jump-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#file-jump-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update suggestions without performing any filesystem access."""
        self.search_request_id += 1
        if len(event.value) < 3:
            self._apply_matches((), False, self.search_request_id)
        else:
            self.search_files(event.value, self.search_request_id)

    @work(exclusive=True, group="file-jump-search")
    async def search_files(self, query: str, token: int) -> None:
        """Match paths off the event loop, coalescing rapid input changes."""
        await asyncio.sleep(0.03)
        matches, truncated = await asyncio.to_thread(
            matching_files, self.files, query
        )
        self._apply_matches(matches, truncated, token)

    def _apply_matches(
        self, matches: tuple[Path, ...], truncated: bool, token: int
    ) -> None:
        """Apply current search results on the event thread."""
        if token != self.search_request_id:
            return
        self.matches = matches
        results = self.query_one("#file-jump-results", OptionList)
        results.clear_options()
        results.add_options(
            Option(str(path), id=str(index))
            for index, path in enumerate(self.matches)
        )
        results.display = bool(self.matches)
        results.styles.height = "auto"
        results.styles.max_height = max(1, self.size.height - 7)
        results.tooltip = (
            f"Showing first {MAX_FILE_JUMP_RESULTS} matches" if truncated else None
        )

    def on_input_submitted(self, _: Input.Submitted) -> None:
        """Choose the first suggestion directly from the search field."""
        if self.matches:
            self.dismiss(self.matches[0])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Choose the selected suggestion."""
        if event.option.id is not None:
            self.dismiss(self.matches[int(event.option.id)])

    def on_key(self, event: events.Key) -> None:
        """Move from the input to suggestions with the down arrow."""
        if event.key != "down" or not isinstance(self.focused, Input):
            return
        results = self.query_one("#file-jump-results", OptionList)
        if results.option_count:
            results.highlighted = 0
            results.focus()
            event.prevent_default()
            event.stop()

    def on_click(self, event: events.Click) -> None:
        """Dismiss when the backdrop outside the dialog is clicked."""
        dialog = self.query_one("#file-jump-dialog")
        if not dialog.region.contains(event.screen_x, event.screen_y):
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


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


class GitPaneApp(App[None]):
    CSS_PATH = "app.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("h", "show_shortcuts", "Help"),
        Binding("1", "show_changes", "Changes"),
        Binding("2", "show_files", "Files"),
        Binding("j", "move_down", "Down"),
        Binding("k", "move_up", "Up"),
        Binding("n", "next_change", "Next change"),
        Binding("p", "previous_change", "Previous change"),
        Binding("s", "stage_file", "Stage/unstage"),
        Binding("d", "discard_file", "Discard"),
        Binding("r", "refresh", "Refresh"),
        Binding("space", "toggle_file", "Toggle"),
        Binding("w", "toggle_wrap", "Wrap"),
        Binding("t", "quick_file_jump", "Jump to file"),
    ]

    def __init__(
        self,
        root: Path,
        cwd: Path | None = None,
        *,
        show_shortcuts: bool = False,
    ) -> None:
        super().__init__()
        self.root = root
        self.cwd = cwd or root
        self.show_shortcuts_on_mount = show_shortcuts
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
        self.diff_change_index: int | None = None
        self.preview_wrapped = False
        self.file_search_index: tuple[tuple[Path, str], ...] = ()
        self.file_nodes: dict[Path, TreeNode[Path]] = {}

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
                        Horizontal(
                            Static(
                                id="diff-title",
                                classes="viewer-title-label",
                                markup=False,
                            ),
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
                        ),
                        CodeView(id="diff-view"),
                        id="diff-pane",
                    ),
                    id="body",
                )
            with TabPane("Files", id="files-tab"):
                yield Horizontal(
                    files_tree,
                    Vertical(
                        Static(
                            id="preview-title", classes="viewer-title", markup=False
                        ),
                        CodeView(id="preview-view"),
                        id="preview-pane",
                    ),
                    id="files-body",
                )
        yield Static(id="branch-status", markup=False)

    def on_mount(self) -> None:
        self.refresh_status()
        self.refresh_history()
        self.refresh_files()
        if self.show_shortcuts_on_mount:
            self.push_screen(ShortcutScreen())

    def action_show_shortcuts(self) -> None:
        self.push_screen(ShortcutScreen())

    def action_show_changes(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "changes-tab"
        staged = self.query_one("#staged-list", ListView)
        unstaged = self.query_one("#unstaged-list", ListView)
        if staged.children:
            staged.focus()
        elif unstaged.children:
            unstaged.focus()
        else:
            self.query_one("#commit-tree", Tree).focus()

    def action_show_files(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "files-tab"
        self.query_one("#files-tree", Tree).focus()

    def action_quick_file_jump(self) -> None:
        """Open the memory-backed file finder from the Files tab."""
        if self.query_one("#main-tabs", TabbedContent).active != "files-tab":
            return
        if self.query_one("#files-tree", Tree).loading:
            return
        self.push_screen(FileJumpScreen(self.file_search_index), self._jump_to_file)

    def _jump_to_file(self, path: Path | None) -> None:
        """Reveal and select a cached file-tree node."""
        if path is None or (node := self.file_nodes.get(path)) is None:
            return
        ancestor = node.parent
        while ancestor is not None:
            ancestor.expand()
            ancestor = ancestor.parent
        self.call_after_refresh(self._select_file_node, node)

    def _select_file_node(self, node: TreeNode[Path]) -> None:
        """Select a revealed file after the expanded tree has laid out."""
        tree = self.query_one("#files-tree", Tree)
        tree.select_node(node)
        tree.scroll_to_node(node, animate=False)
        tree.focus()

    def action_move_down(self) -> None:
        self._move_focused(1)

    def action_move_up(self) -> None:
        self._move_focused(-1)

    def _move_focused(self, offset: int) -> None:
        """Move the selection or scroll the currently focused view."""
        focused = self.focused
        if isinstance(focused, (ListView, Tree)):
            if offset > 0:
                focused.action_cursor_down()
            else:
                focused.action_cursor_up()
        elif isinstance(focused, CodeView):
            focused.scroll_relative(y=offset, animate=False)

    def action_next_change(self) -> None:
        if self.query_one("#main-tabs", TabbedContent).active == "changes-tab":
            self._navigate_diff_change(1)

    def action_previous_change(self) -> None:
        if self.query_one("#main-tabs", TabbedContent).active == "changes-tab":
            self._navigate_diff_change(-1)

    def _focused_file(self) -> FileItem | None:
        """Return the highlighted file when a status list has focus."""
        focused = self.focused
        if not isinstance(focused, ListView):
            return None
        item = focused.highlighted_child
        return item if isinstance(item, FileItem) else None

    def action_stage_file(self) -> None:
        item = self._focused_file()
        if item is None or item.entry.unsupported_reason is not None:
            return
        action = "unstage" if item.entry.side is Side.STAGED else "stage"
        self.apply_entries(action, [item.entry])

    def action_discard_file(self) -> None:
        item = self._focused_file()
        if item is None or item.entry.side is not Side.UNSTAGED:
            return
        self.request_discard([item.entry])

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
            self.query_one("#diff-view", CodeView).set_wrapped(self.diff_wrapped)
        elif active_tab == "files-tab":
            self.preview_wrapped = not self.preview_wrapped
            self.query_one("#preview-view", CodeView).set_wrapped(self.preview_wrapped)

    def on_text_selected(self, _: events.TextSelected) -> None:
        """Copy completed text selections to the terminal clipboard."""
        if selected := self.screen.get_selected_text():
            self.copy_to_clipboard(selected)

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
        if isinstance(self.screen, FileJumpScreen):
            self.screen.dismiss(None)
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
        self.query_one("#preview-view", CodeView).loading = False
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
        file_nodes: dict[Path, TreeNode[Path]] = {}
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
            file_nodes[path] = nodes[parent_parts].add_leaf(
                icons.file_label(parts[-1]), self.cwd / path
            )

        self.file_search_index = tuple((path, str(path).casefold()) for path in files)
        self.file_nodes = file_nodes

        preview = self.query_one("#preview-view", CodeView)
        tree.loading = False
        self.query_one("#preview-title", Static).update("")
        preview.set_document(())
        preview.loading = False

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Start loading the diff for a selected file entry."""
        if not isinstance(event.item, FileItem):
            return
        self.request_diff(event.item.entry)

    def request_diff(self, entry: DiffEntry) -> None:
        """Start loading a working-tree or historical diff."""
        self.selection = entry
        self.query_one("#diff-title", Static).update(entry.path)
        self.diff_change_index = None
        self._update_diff_navigation()
        self.request_id += 1
        if isinstance(entry, FileEntry) and entry.unsupported_reason is not None:
            self.apply_diff_view(
                DiffView((Text(entry.unsupported_reason),), ()), self.request_id
            )
            return
        self.query_one("#diff-view", CodeView).loading = True
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
        self._show_git_error("load diff", error)

    def apply_diff_view(self, view: DiffView, token: int) -> None:
        """Apply a loaded diff view if it is still the current request."""
        if not is_current_request(token, self.request_id):
            return

        self.diff_view = view
        self.diff_change_index = 0 if view.changes else None
        self._update_diff_navigation()
        viewer = self.query_one("#diff-view", CodeView)
        viewer.set_document(view.lines)
        viewer.loading = False
        viewer.scroll_to(0, 0, animate=False)
        if view.first_change is not None:
            self.call_after_refresh(self._scroll_to_diff_change, 0)

    def _clear_diff(self) -> None:
        """Clear the diff viewer and discard the accepted document."""
        self.diff_view = None
        self.diff_change_index = None
        self._update_diff_navigation()
        view = self.query_one("#diff-view", CodeView)
        view.set_document(())
        view.loading = False

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
            self.query_one("#preview-view", CodeView).loading = True
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
        preview = self.query_one("#preview-view", CodeView)
        preview.set_document(view.lines, wrap_indent=view.wrap_indent)
        preview.loading = False

    def on_file_item_selection_changed(self, _: FileItem.SelectionChanged) -> None:
        self._update_bulk_actions()

    def on_file_item_action_requested(self, event: FileItem.ActionRequested) -> None:
        if event.action == "discard":
            self.request_discard([event.entry])
        else:
            self.apply_entries(event.action, [event.entry])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle diff navigation and bulk actions."""
        if event.button.id == "previous-change":
            self._navigate_diff_change(-1)
        elif event.button.id == "next-change":
            self._navigate_diff_change(1)
        elif event.button.id == "stage-selected":
            self.apply_entries("stage", self._checked_entries("#unstaged-list"))
        elif event.button.id == "unstage-selected":
            self.apply_entries("unstage", self._checked_entries("#staged-list"))
        elif event.button.id == "discard-selected":
            self.request_discard(self._checked_entries("#unstaged-list"))

    def _navigate_diff_change(self, offset: int) -> None:
        """Move to an adjacent changed block in the active diff viewer."""
        if self.diff_view is None or self.diff_change_index is None:
            return
        target = self.diff_change_index + offset
        if not 0 <= target < len(self.diff_view.changes):
            return
        self.diff_change_index = target
        self._update_diff_navigation()
        self._scroll_to_diff_change(target)

    def _scroll_to_diff_change(self, index: int) -> None:
        """Scroll to a change, accounting for visual rows in wrapped diffs."""
        if self.diff_view is None:
            return
        row = max(0, self.diff_view.changes[index] - DIFF_CONTEXT_LINES)
        viewer = self.query_one("#diff-view", CodeView)
        viewer.scroll_to(0, viewer.source_to_visual_row(row), animate=False)

    def _update_diff_navigation(self) -> None:
        """Enable navigation buttons when an adjacent change exists."""
        previous = self.query_one("#previous-change", Button)
        next_change = self.query_one("#next-change", Button)
        index = self.diff_change_index
        count = len(self.diff_view.changes) if self.diff_view is not None else 0
        previous.disabled = index is None or index == 0
        next_change.disabled = index is None or index >= count - 1

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
    async def mutate_entries(self, action: str, entries: tuple[FileEntry, ...]) -> None:
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
    GitPaneApp(git.repo_root(cwd), cwd, show_shortcuts=claim_first_launch()).run()


if __name__ == "__main__":
    main()
