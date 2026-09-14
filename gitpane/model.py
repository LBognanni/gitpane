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


@dataclass(frozen=True)
class Commit:
    hash: str
    short_hash: str
    parent: str | None
    subject: str


@dataclass(frozen=True)
class CommitFile:
    path: str
    status: str
    commit_hash: str
    parent: str | None


@dataclass
class RepoState:
    root: Path
    staged: list[FileEntry]
    unstaged: list[FileEntry]
    branch: str = ""
