import os
import subprocess
from pathlib import Path

import pytest

import gitpane.git
from gitpane.git import _parse_commit_files, _parse_commits, _parse_status
from gitpane.model import Commit, CommitFile, FileEntry, Side


def test_parse_status_maps_ordinary_changes() -> None:
    root = Path("/repository")
    output = (
        "1 M. N... 100644 100644 100644 hash hash staged.txt\0"
        "1 .M N... 100644 100644 100644 hash hash unstaged.txt\0"
        "1 AD N... 100644 100644 100644 hash hash both.txt\0"
        "1 T. N... 100644 100644 100644 hash hash type-change.txt\0"
    )

    state = _parse_status(output, root)

    assert state.root == root
    assert state.staged == [
        FileEntry("staged.txt", Side.STAGED, "M"),
        FileEntry("both.txt", Side.STAGED, "A"),
        FileEntry("type-change.txt", Side.STAGED, "M"),
    ]
    assert state.unstaged == [
        FileEntry("unstaged.txt", Side.UNSTAGED, "M"),
        FileEntry("both.txt", Side.UNSTAGED, "D"),
    ]


def test_parse_status_handles_untracked_rename_and_unmerged_records() -> None:
    root = Path("/repository")
    output = (
        "\0? path with spaces.txt\0"
        "2 RM N... 100644 100644 100644 hash hash R100 new.txt\0old.txt\0"
        "u UU N... 100644 100644 100644 100644 hash hash hash conflict.txt\0"
        "x unknown record\0"
        "1 D. N... 100644 100644 100644 hash hash deleted.txt\0\0"
    )

    state = _parse_status(output, root)

    rename_reason = "Rename from old.txt is not supported."
    assert state.staged == [
        FileEntry("new.txt", Side.STAGED, "R", rename_reason),
        FileEntry("deleted.txt", Side.STAGED, "D"),
    ]
    assert state.unstaged == [
        FileEntry("path with spaces.txt", Side.UNSTAGED, "?"),
        FileEntry("new.txt", Side.UNSTAGED, "M", rename_reason),
        FileEntry(
            "conflict.txt",
            Side.UNSTAGED,
            "U",
            "Conflict (UU) resolution is not supported.",
        ),
    ]


def test_parse_status_treats_rename_continuation_as_original_path() -> None:
    state = _parse_status(
        "2 R. N... 100644 100644 100644 hash hash R100 new.txt\0? old.txt\0",
        Path("/repository"),
    )

    assert state.staged == [
        FileEntry(
            "new.txt",
            Side.STAGED,
            "R",
            "Rename from ? old.txt is not supported.",
        )
    ]
    assert state.unstaged == []


def test_parse_status_reports_copies_as_unsupported() -> None:
    state = _parse_status(
        "2 C. N... 100644 100644 100644 hash hash C100 copy.txt\0source.txt\0",
        Path("/repository"),
    )

    assert state.staged == [
        FileEntry(
            "copy.txt",
            Side.STAGED,
            "C",
            "Copy from source.txt is not supported.",
        )
    ]
    assert state.unstaged == []


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("# branch.oid abcdef123456\0# branch.head feature/test\0", "feature/test"),
        (
            "# branch.oid abcdef123456\0# branch.head (detached)\0",
            "detached at abcdef1",
        ),
        ("# branch.oid (initial)\0# branch.head main\0", "main"),
    ],
)
def test_parse_status_reports_branch(output: str, expected: str) -> None:
    assert _parse_status(output, Path("/repository")).branch == expected


def test_status_requests_branch_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_run(root: Path, *args: str) -> str:
        calls.append((root, args))
        return "# branch.oid hash\0# branch.head main\0"

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    state = gitpane.git.status(Path("/repository"))

    assert state.branch == "main"
    assert calls == [
        (
            Path("/repository"),
            (
                "status",
                "--porcelain=v2",
                "--branch",
                "-z",
                "--untracked-files=all",
            ),
        )
    ]


def test_run_preserves_subprocess_settings_and_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="output")

    monkeypatch.setenv("INHERITED_VALUE", "retained")
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert gitpane.git._run(Path("/repository"), "status", "--short") == "output"

    command, kwargs = calls[0]
    assert command == ["git", "--literal-pathspecs", "status", "--short"]
    assert kwargs["cwd"] == Path("/repository")
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "surrogateescape"
    assert kwargs["check"] is False
    assert "shell" not in kwargs
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert environment["INHERITED_VALUE"] == "retained"
    assert environment["GIT_OPTIONAL_LOCKS"] == "0"
    assert os.environ["INHERITED_VALUE"] == "retained"


def test_run_rejects_nonzero_return_codes_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="diff"
        ),
    )

    with pytest.raises(subprocess.CalledProcessError):
        gitpane.git._run(Path("/repository"), "diff")


def test_run_accepts_explicit_return_code_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="diff"
        ),
    )

    assert (
        gitpane.git._run(Path("/repository"), "diff", allowed_returncodes=(0, 1))
        == "diff"
    )


def test_run_rejects_return_code_two_when_one_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 2, stdout="error"
        ),
    )

    with pytest.raises(subprocess.CalledProcessError):
        gitpane.git._run(Path("/repository"), "diff", allowed_returncodes=(0, 1))


def test_error_message_prefers_git_stderr() -> None:
    error = subprocess.CalledProcessError(
        128,
        ["git", "status"],
        stderr="fatal: Unable to create index.lock\n",
    )

    assert gitpane.git.error_message(error) == "fatal: Unable to create index.lock"


@pytest.mark.parametrize(
    ("entry", "expected_args", "expected_kwargs"),
    [
        (
            FileEntry("staged file.txt", Side.STAGED, "M"),
            (
                "diff",
                "--cached",
                "-U9999",
                "--no-color",
                "--no-ext-diff",
                "--",
                "staged file.txt",
            ),
            {},
        ),
        (
            FileEntry("-tracked file.txt", Side.UNSTAGED, "M"),
            (
                "diff",
                "-U9999",
                "--no-color",
                "--no-ext-diff",
                "--",
                "-tracked file.txt",
            ),
            {},
        ),
        (
            FileEntry("-untracked file.txt", Side.UNSTAGED, "?"),
            (
                "diff",
                "--no-index",
                "-U9999",
                "--no-color",
                "--no-ext-diff",
                "--",
                "/dev/null",
                "-untracked file.txt",
            ),
            {"allowed_returncodes": (0, 1)},
        ),
        (
            CommitFile("historical file.txt", "M", "commit", "parent"),
            (
                "diff",
                "-U9999",
                "--no-color",
                "--no-ext-diff",
                "parent",
                "commit",
                "--",
                "historical file.txt",
            ),
            {},
        ),
        (
            CommitFile("initial file.txt", "A", "root", None),
            (
                "show",
                "--format=",
                "-U9999",
                "--no-color",
                "--no-ext-diff",
                "root",
                "--",
                "initial file.txt",
            ),
            {},
        ),
    ],
)
def test_diff_builds_command_and_forwards_output(
    monkeypatch: pytest.MonkeyPatch,
    entry: FileEntry | CommitFile,
    expected_args: tuple[str, ...],
    expected_kwargs: dict[str, tuple[int, int]],
) -> None:
    calls: list[tuple[Path, tuple[str, ...], dict[str, tuple[int, int]]]] = []

    def fake_run(root: Path, *args: str, **kwargs: tuple[int, int]) -> str:
        calls.append((root, args, kwargs))
        return "diff output\n"

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    assert gitpane.git.diff(Path("/repository"), entry) == "diff output\n"
    assert calls == [(Path("/repository"), expected_args, expected_kwargs)]


def test_files_requests_scoped_tracked_and_non_ignored_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_run(cwd: Path, *args: str) -> str:
        calls.append((cwd, args))
        return "z-last.txt\0directory/a file.py\0a-first.txt\0"

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    cwd = Path("/repository/subdirectory")
    assert gitpane.git.files(cwd) == [
        "a-first.txt",
        "directory/a file.py",
        "z-last.txt",
    ]
    assert calls == [
        (
            cwd,
            (
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                ".",
            ),
        )
    ]


def test_parse_commits_keeps_first_parent_and_subject() -> None:
    output = (
        "hash-one\0short-one\0parent-one parent-two\0Merge a branch\0"
        "hash-two\0short-two\0\0Initial commit\0"
    )

    assert _parse_commits(output) == [
        Commit("hash-one", "short-one", "parent-one", "Merge a branch"),
        Commit("hash-two", "short-two", None, "Initial commit"),
    ]


def test_commits_requests_at_most_100_from_current_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, tuple[str, ...], dict[str, tuple[int, ...]]]] = []

    def fake_run(root: Path, *args: str, **kwargs: tuple[int, ...]) -> str:
        calls.append((root, args, kwargs))
        if args[0] == "rev-parse":
            return "hash\n"
        return "hash\0short\0\0Subject\0"

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    assert gitpane.git.commits(Path("/repository")) == [
        Commit("hash", "short", None, "Subject")
    ]
    assert calls == [
        (
            Path("/repository"),
            ("rev-parse", "--verify", "--quiet", "HEAD"),
            {"allowed_returncodes": (0, 1)},
        ),
        (
            Path("/repository"),
            (
                "log",
                "--max-count=100",
                "-z",
                "--format=%H%x00%h%x00%P%x00%s",
            ),
            {},
        )
    ]


def test_commits_skips_log_on_unborn_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(_root: Path, *args: str, **_: object) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    assert gitpane.git.commits(Path("/repository")) == []
    assert calls == [("rev-parse", "--verify", "--quiet", "HEAD")]


def test_parse_commit_files_preserves_status_and_path() -> None:
    commit = Commit("hash", "short", "parent", "Subject")

    assert _parse_commit_files("M\0path with spaces.py\0D\0-old.txt\0", commit) == [
        CommitFile("path with spaces.py", "M", "hash", "parent"),
        CommitFile("-old.txt", "D", "hash", "parent"),
    ]


@pytest.mark.parametrize(
    ("commit", "expected_args"),
    [
        (
            Commit("root-hash", "root", None, "Initial"),
            (
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--name-status",
                "--no-renames",
                "-r",
                "-z",
                "root-hash",
            ),
        ),
        (
            Commit("hash", "short", "parent", "Subject"),
            (
                "diff",
                "--name-status",
                "--no-renames",
                "-z",
                "parent",
                "hash",
            ),
        ),
    ],
)
def test_commit_files_compares_with_first_parent_or_empty_tree(
    monkeypatch: pytest.MonkeyPatch,
    commit: Commit,
    expected_args: tuple[str, ...],
) -> None:
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_run(root: Path, *args: str) -> str:
        calls.append((root, args))
        return "A\0added.txt\0"

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    assert gitpane.git.commit_files(Path("/repository"), commit) == [
        CommitFile("added.txt", "A", commit.hash, commit.parent)
    ]
    assert calls == [(Path("/repository"), expected_args)]


@pytest.mark.parametrize(
    ("operation", "expected_args"),
    [
        (gitpane.git.stage, ("add", "--", "-file with spaces.txt")),
        (
            gitpane.git.restore,
            ("restore", "--worktree", "--", "-file with spaces.txt"),
        ),
        (gitpane.git.clean, ("clean", "-f", "--", "-file with spaces.txt")),
    ],
)
def test_stage_operations_build_commands_and_ignore_output(
    monkeypatch: pytest.MonkeyPatch,
    operation: object,
    expected_args: tuple[str, ...],
) -> None:
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_run(root: Path, *args: str) -> str:
        calls.append((root, args))
        return "nonempty output"

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    assert callable(operation)
    assert operation(Path("/repository"), "-file with spaces.txt") is None
    assert calls == [(Path("/repository"), expected_args)]


@pytest.mark.parametrize(
    "operation",
    [
        gitpane.git.stage,
        gitpane.git.unstage,
        gitpane.git.restore,
        gitpane.git.clean,
    ],
)
def test_stage_operations_propagate_run_errors(
    monkeypatch: pytest.MonkeyPatch, operation: object
) -> None:
    error = subprocess.CalledProcessError(1, ["git", "command"])

    def fake_run(root: Path, *args: str, **_: object) -> str:
        raise error

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    assert callable(operation)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        operation(Path("/repository"), "-file with spaces.txt")

    assert raised.value is error


@pytest.mark.parametrize(
    ("operation", "expected_args"),
    [
        (gitpane.git.stage, ("add", "--", "one.txt", "two.txt")),
    ],
)
def test_stage_operations_accept_multiple_paths(
    monkeypatch: pytest.MonkeyPatch,
    operation: object,
    expected_args: tuple[str, ...],
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(_root: Path, *args: str) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    assert callable(operation)
    operation(Path("/repository"), "one.txt", "two.txt")

    assert calls == [expected_args]


@pytest.mark.parametrize(
    ("head", "expected_args"),
    [
        ("commit-hash\n", ("restore", "--staged", "--", "one.txt", "two.txt")),
        ("", ("rm", "--cached", "-f", "--", "one.txt", "two.txt")),
    ],
)
def test_unstage_handles_existing_and_unborn_heads(
    monkeypatch: pytest.MonkeyPatch,
    head: str,
    expected_args: tuple[str, ...],
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(_root: Path, *args: str, **kwargs: object) -> str:
        calls.append((args, kwargs))
        return head if args[0] == "rev-parse" else ""

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    gitpane.git.unstage(Path("/repository"), "one.txt", "two.txt")

    assert calls == [
        (
            ("rev-parse", "--verify", "--quiet", "HEAD"),
            {"allowed_returncodes": (0, 1)},
        ),
        (expected_args, {}),
    ]
