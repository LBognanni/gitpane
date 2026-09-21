import stat
from dataclasses import dataclass
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text

MAX_PREVIEW_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PreviewView:
    """Prepared, ready-to-render preview lines."""

    lines: tuple[Text, ...]
    wrap_indent: int = 0


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
    syntax = Syntax(source, Syntax.guess_lexer(path.name, source))
    highlighted = list(syntax.highlight(source).split("\n", allow_blank=True))
    highlighted = highlighted[: source.count("\n") + 1]
    number_width = len(str(len(highlighted)))
    lines: list[Text] = []
    for number, highlighted_line in enumerate(highlighted, 1):
        line = Text()
        line.append(f" {number:>{number_width}} ", style="dim")
        line.append_text(highlighted_line)
        lines.append(line)
    return PreviewView(tuple(lines), number_width + 2)
