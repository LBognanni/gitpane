import asyncio
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

import emoji

os.environ.setdefault("TEXTUAL_SMOOTH_SCROLL", "0")

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, ListView, Static, TabbedContent, TabPane, Tree
from textual.widgets.tree import TreeNode

from gitpane import git
from gitpane.diff_view import DiffEntry
from gitpane.model import Commit, CommitFile, FileEntry, RepoState, Side
from gitpane.screens.discard import DiscardScreen
from gitpane.screens.shortcuts import ShortcutScreen, claim_first_launch
from gitpane.widgets import (
    CodeView,
    DiffPane,
    FileBrowser,
    FileItem,
    HorizontalSplitter,
    VerticalSplitter,
)


def format_commit_label(commit: Commit) -> Text:
    """Return a commit subject with gitmoji expanded and its hash last."""
    subject = emoji.emojize(commit.subject, language="alias")
    label = Text(f"{subject} ")
    label.append(commit.short_hash, style="dim")
    return label


def discard_files(root: Path, entries: Sequence[FileEntry]) -> None:
    """Discard tracked changes and remove untracked entries."""
    tracked = [entry.path for entry in entries if entry.status != "?"]
    untracked = [entry.path for entry in entries if entry.status == "?"]
    if tracked:
        git.restore(root, *tracked)
    if untracked:
        git.clean(root, *untracked)


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
        self.status_request_id = 0
        self.history_request_id = 0
        self.commit_files_request_id = 0
        self.mutation_lock = asyncio.Lock()
        self.status_apply_lock = asyncio.Lock()
        self.history_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        commit_tree: Tree[Commit | CommitFile] = Tree("", id="commit-tree")
        commit_tree.show_root = False
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
                    DiffPane(self.root, self._show_git_error),
                    id="body",
                )
            with TabPane("Files", id="files-tab"):
                yield FileBrowser(self.root, self.cwd, self._show_git_error)
        yield Static(id="branch-status", markup=False)

    @property
    def diff_pane(self) -> DiffPane:
        return self.query_one(DiffPane)

    @property
    def file_browser(self) -> FileBrowser:
        return self.query_one(FileBrowser)

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
        if self.query_one("#main-tabs", TabbedContent).active == "files-tab":
            self.file_browser.quick_jump()

    def action_move_down(self) -> None:
        self._move_focused(1)

    def action_move_up(self) -> None:
        self._move_focused(-1)

    def _move_focused(self, offset: int) -> None:
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
            self.diff_pane.navigate(1)

    def action_previous_change(self) -> None:
        if self.query_one("#main-tabs", TabbedContent).active == "changes-tab":
            self.diff_pane.navigate(-1)

    def _focused_file(self) -> FileItem | None:
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
        if item is not None and item.entry.side is Side.UNSTAGED:
            self.request_discard([item.entry])

    def action_refresh(self) -> None:
        self.refresh_status()
        self.refresh_history()
        self.refresh_files()

    def action_toggle_file(self) -> None:
        item = self._focused_file()
        if item is not None:
            item.toggle_checked()

    def action_toggle_wrap(self) -> None:
        active_tab = self.query_one("#main-tabs", TabbedContent).active
        if active_tab == "changes-tab":
            self.diff_pane.toggle_wrap()
        elif active_tab == "files-tab":
            self.file_browser.toggle_wrap()

    def on_text_selected(self, _: events.TextSelected) -> None:
        if selected := self.screen.get_selected_text():
            self.copy_to_clipboard(selected)

    def refresh_status(self) -> None:
        token = self._start_status_refresh()
        self.load_status(token)

    def _start_status_refresh(self) -> int:
        self.status_request_id += 1
        self.diff_pane.invalidate(clear=False)
        self.query_one("#staged-list", ListView).loading = True
        self.query_one("#unstaged-list", ListView).loading = True
        return self.status_request_id

    @work(group="status")
    async def load_status(self, token: int) -> None:
        try:
            async with self.mutation_lock:
                if token != self.status_request_id:
                    return
                state = await asyncio.to_thread(git.status, self.root)
        except (subprocess.SubprocessError, OSError) as error:
            self.apply_status_error(error, token)
            return
        await self.apply_status(state, token)

    def apply_status_error(
        self, error: subprocess.SubprocessError | OSError, token: int
    ) -> None:
        if token != self.status_request_id:
            return
        self.query_one("#staged-list", ListView).loading = False
        self.query_one("#unstaged-list", ListView).loading = False
        self.diff_pane.stop_loading()
        self._show_git_error("refresh status", error)

    async def apply_status(self, state: RepoState, token: int) -> None:
        async with self.status_apply_lock:
            if token != self.status_request_id:
                return
            staged_list = self.query_one("#staged-list", ListView)
            unstaged_list = self.query_one("#unstaged-list", ListView)
            await staged_list.clear()
            await unstaged_list.clear()
            await staged_list.extend(FileItem(entry) for entry in state.staged)
            await unstaged_list.extend(FileItem(entry) for entry in state.unstaged)
            staged_list.loading = False
            unstaged_list.loading = False
            self._update_bulk_actions()
            self.query_one("#branch-status", Static).update(f"Branch: {state.branch}")
            self.diff_pane.invalidate()
            if state.staged:
                staged_list.index = 0
                staged_list.focus()
            elif state.unstaged:
                unstaged_list.index = 0
                unstaged_list.focus()

    def refresh_history(self) -> None:
        self.history_request_id += 1
        self.commit_files_request_id += 1
        self.query_one("#commit-tree", Tree).loading = True
        self.load_history(self.history_request_id)

    @work(group="history")
    async def load_history(self, token: int) -> None:
        try:
            async with self.history_lock:
                if token != self.history_request_id:
                    return
                commits = await asyncio.to_thread(git.commits, self.root)
        except (subprocess.SubprocessError, OSError) as error:
            self.apply_history_error(error, token)
            return
        self.apply_history(commits, token)

    def apply_history_error(
        self, error: subprocess.SubprocessError | OSError, token: int
    ) -> None:
        if token != self.history_request_id:
            return
        self.query_one("#commit-tree", Tree).loading = False
        self._show_git_error("refresh history", error)

    def apply_history(self, commits: list[Commit], token: int) -> None:
        if token != self.history_request_id:
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
        self.file_browser.refresh_files()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, FileItem):
            self.request_diff(event.item.entry)

    def request_diff(self, entry: DiffEntry) -> None:
        self.diff_pane.request(entry)

    def on_tree_node_selected(self, event: Tree.NodeSelected[object]) -> None:
        if event.control.id == "files-tree":
            return
        if isinstance(event.node.data, CommitFile):
            self.request_diff(event.node.data)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[object]) -> None:
        if event.control.id == "files-tree":
            return
        commit = event.node.data
        if not isinstance(commit, Commit) or event.node.children:
            return
        self.commit_files_request_id += 1
        self.query_one("#commit-tree", Tree).loading = True
        self.load_commit_files(commit, event.node, self.commit_files_request_id)

    @work(thread=True, exclusive=True, group="commit-files")
    def load_commit_files(
        self, commit: Commit, node: TreeNode[object], token: int
    ) -> None:
        try:
            entries = git.commit_files(self.root, commit)
        except (subprocess.SubprocessError, OSError) as error:
            self.call_from_thread(self.apply_commit_files_error, error, token)
            return
        self.call_from_thread(self.apply_commit_files, entries, node, token)

    def apply_commit_files_error(
        self, error: subprocess.SubprocessError | OSError, token: int
    ) -> None:
        if token != self.commit_files_request_id:
            return
        self.query_one("#commit-tree", Tree).loading = False
        self._show_git_error("load commit files", error)

    def apply_commit_files(
        self, entries: list[CommitFile], node: TreeNode[object], token: int
    ) -> None:
        if token != self.commit_files_request_id:
            return
        tree = self.query_one("#commit-tree", Tree)
        tree.loading = False
        for entry in entries:
            node.add_leaf(Text(f"{entry.status} {entry.path}"), entry)
        if not entries:
            node.add_leaf(Text("(no changed files)"))

    def on_file_item_selection_changed(self, _: FileItem.SelectionChanged) -> None:
        self._update_bulk_actions()

    def on_file_item_action_requested(self, event: FileItem.ActionRequested) -> None:
        if event.action == "discard":
            self.request_discard([event.entry])
        else:
            self.apply_entries(event.action, [event.entry])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stage-selected":
            self.apply_entries("stage", self._checked_entries("#unstaged-list"))
        elif event.button.id == "unstage-selected":
            self.apply_entries("unstage", self._checked_entries("#staged-list"))
        elif event.button.id == "discard-selected":
            self.request_discard(self._checked_entries("#unstaged-list"))

    def _checked_entries(self, selector: str) -> list[FileEntry]:
        return [
            item.entry
            for item in self.query_one(selector, ListView).children
            if isinstance(item, FileItem) and item.checked
        ]

    def _update_bulk_actions(self) -> None:
        staged = bool(self._checked_entries("#staged-list"))
        unstaged = bool(self._checked_entries("#unstaged-list"))
        self.query_one("#staged-actions").set_class(staged, "has-selection")
        self.query_one("#unstaged-actions").set_class(unstaged, "has-selection")
        self.query_one("#unstage-selected", Button).disabled = not staged
        self.query_one("#stage-selected", Button).disabled = not unstaged
        self.query_one("#discard-selected", Button).disabled = not unstaged

    def apply_entries(self, action: str, entries: Sequence[FileEntry]) -> None:
        supported = tuple(
            entry for entry in entries if entry.unsupported_reason is None
        )
        if supported:
            self.mutate_entries(action, supported)

    @work(group="mutations")
    async def mutate_entries(self, action: str, entries: tuple[FileEntry, ...]) -> None:
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
        selected = tuple(
            entry for entry in entries if entry.unsupported_reason is None
        )
        if not selected:
            return

        def finish(confirmed: bool | None) -> None:
            if confirmed:
                self.mutate_entries("discard", selected)

        self.push_screen(DiscardScreen(selected), finish)

    def _show_git_error(
        self, action: str, error: subprocess.SubprocessError | OSError
    ) -> None:
        self.notify(
            git.error_message(error),
            title=f"Could not {action}",
            severity="error",
        )


def main() -> None:
    cwd = Path.cwd()
    GitPaneApp(git.repo_root(cwd), cwd, show_shortcuts=claim_first_launch()).run()


if __name__ == "__main__":
    main()
