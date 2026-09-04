"""Git status discovery and porcelain parsing."""

import os
import subprocess
from pathlib import Path

from gitpane.model import FileEntry, RepoState, Side


def _run(cwd: Path, *args: str, allowed_returncodes: tuple[int, ...] = (0,)) -> str:
    """Run a Git command in *cwd* and return its standard output."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=False,
        text=True,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode not in allowed_returncodes:
        result.check_returncode()
    return result.stdout


def repo_root(path: Path | None = None) -> Path:
    """Return the root of the repository containing *path*."""
    return Path(_run(path or Path.cwd(), "rev-parse", "--show-toplevel").strip())


def _parse_status(output: str, root: Path) -> RepoState:
    staged: list[FileEntry] = []
    unstaged: list[FileEntry] = []

    records = iter(output.split("\0"))
    for record in records:
        if not record:
            continue
        if record.startswith("1 "):
            fields = record.split(" ", maxsplit=8)
            if len(fields) != 9:
                continue
            if len(fields[1]) != 2:
                continue
            x, y, path = fields[1][0], fields[1][1], fields[8]
            for code, side, entries in (
                (x, Side.STAGED, staged),
                (y, Side.UNSTAGED, unstaged),
            ):
                if code in "AMD":
                    entries.append(FileEntry(path, side, code))
                elif code == "T":
                    entries.append(FileEntry(path, side, "M"))
        elif record.startswith("? "):
            unstaged.append(FileEntry(record[2:], Side.UNSTAGED, "?"))
        elif record.startswith("2 "):
            next(records, None)

    return RepoState(root, staged, unstaged)


def status(root: Path) -> RepoState:
    """Return the parsed Git status for *root*."""
    return _parse_status(
        _run(root, "status", "--porcelain=v2", "-z", "--untracked-files=all"), root
    )


def diff(root: Path, entry: FileEntry) -> str:
    """Return the full Git diff for *entry*."""
    if entry.side is Side.STAGED:
        return _run(
            root,
            "diff",
            "--cached",
            "-U9999",
            "--no-color",
            "--no-ext-diff",
            "--",
            entry.path,
        )
    if entry.status == "?":
        return _run(
            root,
            "diff",
            "--no-index",
            "-U9999",
            "--no-color",
            "--no-ext-diff",
            "--",
            "/dev/null",
            entry.path,
            allowed_returncodes=(0, 1),
        )
    return _run(root, "diff", "-U9999", "--no-color", "--no-ext-diff", "--", entry.path)


def main() -> None:
    """Print Git status for the current repository."""
    state = status(repo_root())
    print("Staged:")
    for entry in state.staged:
        print(f"{entry.status} {entry.path}")
    print("Unstaged:")
    for entry in state.unstaged:
        print(f"{entry.status} {entry.path}")


if __name__ == "__main__":
    main()
