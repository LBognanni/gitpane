"""Git status discovery and porcelain parsing."""

import os
import subprocess
from pathlib import Path

from gitpane.model import Commit, CommitFile, FileEntry, RepoState, Side

MAX_COMMITS = 100


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
    branch = ""
    oid = ""

    records = iter(output.split("\0"))
    for record in records:
        if not record:
            continue
        if record.startswith("# branch.head "):
            branch = record.removeprefix("# branch.head ")
        elif record.startswith("# branch.oid "):
            oid = record.removeprefix("# branch.oid ")
        elif record.startswith("1 "):
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

    if branch == "(detached)" and oid:
        branch = f"detached at {oid[:7]}"
    return RepoState(root, staged, unstaged, branch)


def status(root: Path) -> RepoState:
    """Return the parsed Git status for *root*."""
    return _parse_status(
        _run(
            root,
            "status",
            "--porcelain=v2",
            "--branch",
            "-z",
            "--untracked-files=all",
        ),
        root,
    )


def files(cwd: Path) -> list[str]:
    """Return tracked and non-ignored untracked files below *cwd*."""
    output = _run(
        cwd,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        ".",
    )
    return sorted(path for path in output.split("\0") if path)


def _parse_commits(output: str) -> list[Commit]:
    """Parse NUL-delimited commit metadata from ``git log``."""
    fields = output.split("\0")
    commits: list[Commit] = []
    for index in range(0, len(fields) - 3, 4):
        commit_hash, short_hash, parents, subject = fields[index : index + 4]
        if not commit_hash:
            continue
        commits.append(
            Commit(
                commit_hash,
                short_hash,
                parents.split(" ", maxsplit=1)[0] if parents else None,
                subject,
            )
        )
    return commits


def commits(root: Path) -> list[Commit]:
    """Return up to 100 commits reachable from the current branch."""
    output = _run(
        root,
        "log",
        f"--max-count={MAX_COMMITS}",
        "-z",
        "--format=%H%x00%h%x00%P%x00%s",
        allowed_returncodes=(0, 128),
    )
    return _parse_commits(output)


def _parse_commit_files(output: str, commit: Commit) -> list[CommitFile]:
    """Parse NUL-delimited name/status pairs for one commit."""
    fields = output.split("\0")
    return [
        CommitFile(path, status[0], commit.hash, commit.parent)
        for status, path in zip(fields[::2], fields[1::2])
        if status and path
    ]


def commit_files(root: Path, commit: Commit) -> list[CommitFile]:
    """Return files changed by *commit* relative to its first parent."""
    if commit.parent is None:
        output = _run(
            root,
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "--no-renames",
            "-r",
            "-z",
            commit.hash,
        )
    else:
        output = _run(
            root,
            "diff",
            "--name-status",
            "--no-renames",
            "-z",
            commit.parent,
            commit.hash,
        )
    return _parse_commit_files(output, commit)


def diff(root: Path, entry: FileEntry | CommitFile) -> str:
    """Return the full Git diff for *entry*."""
    if isinstance(entry, CommitFile):
        if entry.parent is None:
            return _run(
                root,
                "show",
                "--format=",
                "-U9999",
                "--no-color",
                "--no-ext-diff",
                entry.commit_hash,
                "--",
                entry.path,
            )
        return _run(
            root,
            "diff",
            "-U9999",
            "--no-color",
            "--no-ext-diff",
            entry.parent,
            entry.commit_hash,
            "--",
            entry.path,
        )
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


def stage(root: Path, *paths: str) -> None:
    """Stage *paths* in *root*."""
    _run(root, "add", "--", *paths)


def unstage(root: Path, *paths: str) -> None:
    """Unstage *paths* in *root*."""
    _run(root, "restore", "--staged", "--", *paths)


def restore(root: Path, *paths: str) -> None:
    """Discard working-tree changes to tracked *paths*."""
    _run(root, "restore", "--worktree", "--", *paths)


def clean(root: Path, *paths: str) -> None:
    """Remove untracked *paths* from the working tree."""
    _run(root, "clean", "-f", "--", *paths)


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
