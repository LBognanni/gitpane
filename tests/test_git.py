import os
import subprocess
from pathlib import Path

import pytest

import gitpane.git
from gitpane.git import _parse_status
from gitpane.model import FileEntry, Side


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


def test_parse_status_handles_untracked_and_unsupported_records() -> None:
    root = Path("/repository")
    output = (
        "\0? path with spaces.txt\0"
        "2 R. N... 100644 100644 100644 hash hash score new.txt\0old.txt\0"
        "u UU N... 100644 100644 100644 100644 hash hash hash conflict.txt\0"
        "x unknown record\0"
        "1 D. N... 100644 100644 100644 hash hash deleted.txt\0\0"
    )

    state = _parse_status(output, root)

    assert state.staged == [FileEntry("deleted.txt", Side.STAGED, "D")]
    assert state.unstaged == [FileEntry("path with spaces.txt", Side.UNSTAGED, "?")]


def test_parse_status_skips_rename_continuation() -> None:
    state = _parse_status(
        "2 R. N... 100644 100644 100644 hash hash score new.txt\0? phantom.txt\0",
        Path("/repository"),
    )

    assert state.staged == []
    assert state.unstaged == []


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
    assert command == ["git", "status", "--short"]
    assert kwargs["cwd"] == Path("/repository")
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
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
    ],
)
def test_diff_builds_command_and_forwards_output(
    monkeypatch: pytest.MonkeyPatch,
    entry: FileEntry,
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


@pytest.mark.parametrize(
    ("operation", "expected_args"),
    [
        (gitpane.git.stage, ("add", "--", "-file with spaces.txt")),
        (
            gitpane.git.unstage,
            ("restore", "--staged", "--", "-file with spaces.txt"),
        ),
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


@pytest.mark.parametrize("operation", [gitpane.git.stage, gitpane.git.unstage])
def test_stage_operations_propagate_run_errors(
    monkeypatch: pytest.MonkeyPatch, operation: object
) -> None:
    error = subprocess.CalledProcessError(1, ["git", "command"])

    def fake_run(root: Path, *args: str) -> str:
        raise error

    monkeypatch.setattr(gitpane.git, "_run", fake_run)

    assert callable(operation)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        operation(Path("/repository"), "-file with spaces.txt")

    assert raised.value is error
