import asyncio
import subprocess
from collections.abc import Callable
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Tree
from textual.widgets.tree import TreeNode

from gitpane import git, icons
from gitpane.preview import PreviewView, load_preview_view
from gitpane.screens.file_jump import FileJumpScreen
from gitpane.widgets.code_view import CodeView

ErrorHandler = Callable[[str, subprocess.SubprocessError | OSError], None]


class FileBrowser(Horizontal):
    """Own repository file discovery, jumping, and file previews."""

    def __init__(self, root: Path, cwd: Path, on_error: ErrorHandler) -> None:
        super().__init__(id="files-body")
        self.root = root
        self.cwd = cwd
        self.on_error = on_error
        self.files_request_id = 0
        self.preview_request_id = 0
        self.files_lock = asyncio.Lock()
        self.wrapped = False
        self.search_index: tuple[tuple[Path, str], ...] = ()
        self.file_nodes: dict[Path, TreeNode[Path]] = {}

    def compose(self) -> ComposeResult:
        tree: Tree[Path] = Tree(
            icons.folder_label(str(self.cwd), expanded=True), self.cwd, id="files-tree"
        )
        tree.guide_depth = 3
        yield tree
        yield Vertical(
            Static(id="preview-title", classes="viewer-title", markup=False),
            CodeView(id="preview-view"),
            id="preview-pane",
        )

    def refresh_files(self) -> None:
        if isinstance(self.app.screen, FileJumpScreen):
            self.app.screen.dismiss(None)
        self.files_request_id += 1
        self.preview_request_id += 1
        self.query_one("#files-tree", Tree).loading = True
        self.load_files(self.files_request_id)

    @work(group="files")
    async def load_files(self, token: int) -> None:
        try:
            async with self.files_lock:
                if token != self.files_request_id:
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
        if token != self.files_request_id:
            return
        self.query_one("#files-tree", Tree).loading = False
        self.query_one("#preview-view", CodeView).loading = False
        self.on_error("refresh files", error)

    def apply_files(self, files: list[Path], token: int) -> None:
        if token != self.files_request_id:
            return
        self.preview_request_id += 1
        tree = self.query_one("#files-tree", Tree)
        tree.clear()
        tree.root.set_label(icons.folder_label(str(self.cwd), expanded=True))
        tree.root.expand()
        nodes: dict[tuple[str, ...], TreeNode[Path]] = {(): tree.root}
        file_nodes: dict[Path, TreeNode[Path]] = {}
        for path in files:
            parent_parts: tuple[str, ...] = ()
            for part in path.parts[:-1]:
                branch_parts = (*parent_parts, part)
                if branch_parts not in nodes:
                    directory = self.cwd.joinpath(*branch_parts)
                    nodes[branch_parts] = nodes[parent_parts].add(
                        icons.folder_label(part, expanded=False), directory
                    )
                parent_parts = branch_parts
        for path in files:
            parent_parts = path.parts[:-1]
            file_nodes[path] = nodes[parent_parts].add_leaf(
                icons.file_label(path.parts[-1]), self.cwd / path
            )
        self.search_index = tuple((path, str(path).casefold()) for path in files)
        self.file_nodes = file_nodes
        preview = self.query_one("#preview-view", CodeView)
        tree.loading = False
        self.query_one("#preview-title", Static).update("")
        preview.set_document(())
        preview.loading = False

    def quick_jump(self) -> None:
        tree = self.query_one("#files-tree", Tree)
        if tree.loading:
            return
        self.app.push_screen(FileJumpScreen(self.search_index), self._jump_to_file)

    def _jump_to_file(self, path: Path | None) -> None:
        if path is None or (node := self.file_nodes.get(path)) is None:
            return
        ancestor = node.parent
        while ancestor is not None:
            ancestor.expand()
            ancestor = ancestor.parent
        self.call_after_refresh(self._select_file_node, node)

    def _select_file_node(self, node: TreeNode[Path]) -> None:
        tree = self.query_one("#files-tree", Tree)
        tree.select_node(node)
        tree.scroll_to_node(node, animate=False)
        tree.focus()

    def on_tree_node_selected(self, event: Tree.NodeSelected[Path]) -> None:
        if event.control.id != "files-tree":
            return
        data = event.node.data
        if event.node.allow_expand or not isinstance(data, Path):
            return
        self.preview_request_id += 1
        self.query_one("#preview-title", Static).update(str(data.relative_to(self.root)))
        self.query_one("#preview-view", CodeView).loading = True
        self.load_preview(data, self.preview_request_id)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[Path]) -> None:
        path = event.node.data
        if isinstance(path, Path):
            name = str(self.cwd) if event.node is event.control.root else path.name
            event.node.set_label(icons.folder_label(name, expanded=True))

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[Path]) -> None:
        path = event.node.data
        if isinstance(path, Path):
            name = str(self.cwd) if event.node is event.control.root else path.name
            event.node.set_label(icons.folder_label(name, expanded=False))

    @work(thread=True, exclusive=True, group="preview")
    def load_preview(self, path: Path, token: int) -> None:
        self.app.call_from_thread(self.apply_preview, load_preview_view(path), token)

    def apply_preview(self, view: PreviewView, token: int) -> None:
        if token != self.preview_request_id:
            return
        preview = self.query_one("#preview-view", CodeView)
        preview.set_document(view.lines, wrap_indent=view.wrap_indent)
        preview.loading = False

    def toggle_wrap(self) -> None:
        self.wrapped = not self.wrapped
        self.query_one("#preview-view", CodeView).set_wrapped(self.wrapped)
