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

GitPane supports whole-file staging and unstaging plus unified diffs. It does
not yet support hunk or line staging, commits, conflict resolution, renames,
binary files, syntax highlighting, or automatic file watching.
