from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Side(Enum):
    STAGED = "staged"
    UNSTAGED = "unstaged"


@dataclass(frozen=True)
class FileEntry:
    path: str
    side: Side
    status: str


@dataclass
class RepoState:
    root: Path
    staged: list[FileEntry]
    unstaged: list[FileEntry]
