# gitpane

A terminal Git status and diff viewer built with Python and Textual. It shows
staged and unstaged files in a split view, displays full-context unified diffs,
and can stage or unstage whole files.

## Requirements

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/)
- Git

Run GitPane from inside a Git repository.

## Install And Run

Install GitPane as a `uv` tool so the `gitpane` command is available in any
repository:

```bash
uv tool install git+https://github.com/LBognanni/gitpane
gitpane
```

To work on GitPane itself, clone the repository and run it from source
instead:

```bash
uv sync --dev
uv run python -m gitpane.app
```

The left pane lists staged files first, then unstaged files. Select a file to
show its diff in the right pane. Long lines can be scrolled horizontally.

## Controls

| Control | Action |
| --- | --- |
| Up/Down | Move through the focused file list |
| Enter or click a file | Load its diff |
| Space | Stage the focused unstaged file, or unstage the focused staged file |
| Click `[ ]` | Stage or unstage that file |
| `r` | Refresh repository status |

## Current Scope

GitPane supports whole-file staging and unstaging plus syntax-highlighted,
unified diffs in an accessible dark theme. It does not yet support hunk or
line staging, commits, conflict resolution, renames, binary files, or
automatic file watching.
