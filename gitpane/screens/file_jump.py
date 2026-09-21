import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from textual import events, work
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

MAX_FILE_JUMP_RESULTS = 100


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
        self.search_request_id += 1
        if len(event.value) < 3:
            self._apply_matches((), False, self.search_request_id)
        else:
            self.search_files(event.value, self.search_request_id)

    @work(exclusive=True, group="file-jump-search")
    async def search_files(self, query: str, token: int) -> None:
        await asyncio.sleep(0.03)
        matches, truncated = await asyncio.to_thread(matching_files, self.files, query)
        self._apply_matches(matches, truncated, token)

    def _apply_matches(
        self, matches: tuple[Path, ...], truncated: bool, token: int
    ) -> None:
        if token != self.search_request_id:
            return
        self.matches = matches
        results = self.query_one("#file-jump-results", OptionList)
        results.clear_options()
        results.add_options(
            Option(str(path), id=str(index)) for index, path in enumerate(self.matches)
        )
        results.display = bool(self.matches)
        results.styles.height = "auto"
        results.styles.max_height = max(1, self.size.height - 7)
        results.tooltip = (
            f"Showing first {MAX_FILE_JUMP_RESULTS} matches" if truncated else None
        )

    def on_input_submitted(self, _: Input.Submitted) -> None:
        if self.matches:
            self.dismiss(self.matches[0])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is not None:
            self.dismiss(self.matches[int(event.option.id)])

    def on_key(self, event: events.Key) -> None:
        if event.key != "down" or not isinstance(self.focused, Input):
            return
        results = self.query_one("#file-jump-results", OptionList)
        if results.option_count:
            results.highlighted = 0
            results.focus()
            event.prevent_default()
            event.stop()

    def on_click(self, event: events.Click) -> None:
        dialog = self.query_one("#file-jump-dialog")
        if not dialog.region.contains(event.screen_x, event.screen_y):
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
