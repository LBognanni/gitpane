import functools
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text

from gitpane import diff, git
from gitpane.diff import Row
from gitpane.model import CommitFile, FileEntry

DiffEntry = FileEntry | CommitFile
DIFF_CONTEXT_LINES = 4


@dataclass(frozen=True)
class DiffView:
    """A prepared, ready-to-render diff for one file entry."""

    lines: tuple[Text, ...]
    changes: tuple[int, ...]

    @property
    def first_change(self) -> int | None:
        return self.changes[0] if self.changes else None


@functools.lru_cache(maxsize=4)
def build_diff_view(entry: DiffEntry, patch: str) -> DiffView:
    """Build the prepared diff view for an entry's patch text."""
    rows = diff.parse(patch)
    return DiffView(render_diff_rows(entry, rows), diff.change_indices(rows))


def load_diff_view(root: Path, entry: DiffEntry) -> DiffView:
    """Load the diff for an entry and return its prepared view."""
    return build_diff_view(entry, git.diff(root, entry))


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
