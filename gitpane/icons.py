"""Nerd Font labels for the filesystem tree."""

from pathlib import Path

from rich.text import Text

Icon = tuple[str, str]

FOLDER_CLOSED: Icon = ("", "#03a9f4")
FOLDER_OPEN: Icon = ("", "#03a9f4")
DEFAULT_FILE: Icon = ("", "#f0f3f6")

FILE_NAMES: dict[str, Icon] = {
    ".dockerignore": ("󰡨", "#458ee6"),
    ".env": ("", "#faf743"),
    ".gitattributes": ("", "#f54d27"),
    ".gitignore": ("", "#f54d27"),
    ".gitmodules": ("", "#f54d27"),
    "cargo.lock": ("", "#dea584"),
    "cargo.toml": ("", "#dea584"),
    "compose.yaml": ("󰡨", "#458ee6"),
    "compose.yml": ("󰡨", "#458ee6"),
    "docker-compose.yaml": ("󰡨", "#458ee6"),
    "docker-compose.yml": ("󰡨", "#458ee6"),
    "dockerfile": ("󰡨", "#458ee6"),
    "gemfile": ("", "#cc342d"),
    "go.mod": ("", "#00add8"),
    "go.sum": ("", "#00add8"),
    "justfile": ("", "#b1bac4"),
    "license": ("", "#d0bf41"),
    "license.md": ("", "#d0bf41"),
    "makefile": ("", "#b1bac4"),
    "package-lock.json": ("", "#e8274b"),
    "package.json": ("", "#e8274b"),
    "pnpm-lock.yaml": ("", "#f9ad02"),
    "pyproject.toml": ("", "#ffbc03"),
    "readme": ("󰂺", "#ededed"),
    "readme.md": ("󰂺", "#ededed"),
    "uv.lock": ("", "#ffbc03"),
    "yarn.lock": ("", "#2c8ebb"),
}

FILE_EXTENSIONS: dict[str, Icon] = {
    ".7z": ("", "#eca517"),
    ".avi": ("", "#fd971f"),
    ".bash": ("", "#89e051"),
    ".bmp": ("", "#a074c4"),
    ".bz2": ("", "#eca517"),
    ".c": ("", "#599eff"),
    ".cc": ("", "#f34b7d"),
    ".conf": ("", "#b1bac4"),
    ".cpp": ("", "#519aba"),
    ".cs": ("󰌛", "#9b4f96"),
    ".css": ("", "#a074c4"),
    ".csv": ("", "#89e051"),
    ".dart": ("", "#46a5d9"),
    ".db": ("", "#dad8d8"),
    ".diff": ("", "#6e7681"),
    ".doc": ("󰈬", "#519aba"),
    ".docx": ("󰈬", "#519aba"),
    ".erl": ("", "#b83998"),
    ".ex": ("", "#a074c4"),
    ".exs": ("", "#a074c4"),
    ".fish": ("", "#89e051"),
    ".gif": ("", "#a074c4"),
    ".go": ("", "#00add8"),
    ".gz": ("", "#eca517"),
    ".h": ("", "#a074c4"),
    ".hpp": ("", "#a074c4"),
    ".hs": ("", "#a074c4"),
    ".htm": ("", "#e44d26"),
    ".html": ("", "#e44d26"),
    ".ini": ("", "#b1bac4"),
    ".java": ("", "#cc3e44"),
    ".jpeg": ("", "#a074c4"),
    ".jpg": ("", "#a074c4"),
    ".js": ("", "#cbcb41"),
    ".json": ("", "#cbcb41"),
    ".jsx": ("", "#20c2e3"),
    ".kt": ("", "#a074c4"),
    ".kts": ("", "#a074c4"),
    ".less": ("", "#519aba"),
    ".lock": ("", "#b1bac4"),
    ".log": ("󰌱", "#b1bac4"),
    ".lua": ("", "#51a0cf"),
    ".md": ("", "#dddddd"),
    ".mjs": ("", "#f1e05a"),
    ".mkv": ("", "#fd971f"),
    ".mov": ("", "#fd971f"),
    ".mp3": ("", "#00afff"),
    ".mp4": ("", "#fd971f"),
    ".nix": ("", "#7ebae4"),
    ".pdf": ("", "#e5534b"),
    ".php": ("", "#a074c4"),
    ".png": ("", "#a074c4"),
    ".ppt": ("󰈧", "#e26b45"),
    ".pptx": ("󰈧", "#e26b45"),
    ".py": ("", "#ffbc03"),
    ".pyi": ("", "#ffbc03"),
    ".rar": ("", "#eca517"),
    ".rb": ("", "#cc342d"),
    ".rs": ("", "#dea584"),
    ".sass": ("", "#f55385"),
    ".scala": ("", "#cc3e44"),
    ".scss": ("", "#f55385"),
    ".sh": ("", "#89e051"),
    ".sql": ("", "#dad8d8"),
    ".sqlite": ("", "#dad8d8"),
    ".svelte": ("", "#ff3e00"),
    ".svg": ("󰜡", "#ffb13b"),
    ".swift": ("", "#e37933"),
    ".tar": ("", "#eca517"),
    ".tf": ("", "#7b42bc"),
    ".toml": ("", "#d06b3c"),
    ".ts": ("", "#519aba"),
    ".tsx": ("", "#20c2e3"),
    ".txt": ("󰈙", "#89e051"),
    ".vue": ("", "#8dc149"),
    ".wav": ("", "#00afff"),
    ".webp": ("", "#a074c4"),
    ".xls": ("󰈛", "#3c9b64"),
    ".xlsx": ("󰈛", "#3c9b64"),
    ".xml": ("󰗀", "#e37933"),
    ".xz": ("", "#eca517"),
    ".yaml": ("", "#b1bac4"),
    ".yml": ("", "#b1bac4"),
    ".zig": ("", "#f69a1b"),
    ".zip": ("", "#eca517"),
    ".zsh": ("", "#89e051"),
}


def _label(icon: Icon, name: str) -> Text:
    glyph, color = icon
    label = Text(glyph)
    label.stylize(color, 0, len(label))
    label.append(f" {name}")
    return label


def file_label(name: str) -> Text:
    """Return a colored Nerd Font label selected by filename or extension."""
    normalized = name.casefold()
    icon = FILE_NAMES.get(normalized)
    if icon is None:
        icon = FILE_EXTENSIONS.get(Path(normalized).suffix, DEFAULT_FILE)
    return _label(icon, name)


def folder_label(name: str, *, expanded: bool) -> Text:
    """Return an open or closed folder label."""
    return _label(FOLDER_OPEN if expanded else FOLDER_CLOSED, name)
