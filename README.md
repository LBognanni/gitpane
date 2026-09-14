# gitpane

A terminal Git status, history, diff, and file browser built with Python and
Textual. It shows staged and unstaged files, displays full-context unified
diffs, previews repository files, and can stage or unstage whole files.

## Requirements

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/)
- Git
- A [Nerd Font](https://www.nerdfonts.com/) configured in your terminal

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

The **Changes** tab lists staged files, unstaged files, and up to 100 recent
commits from the current branch. Select a commit to expand its changed files,
then select a file to show its historical diff. The selected file is shown
above each viewer, and the current branch appears in the bottom status bar. The
**Files** tab shows tracked and non-ignored untracked files below the directory
where GitPane was launched; select one for a syntax-highlighted preview. Long
lines scroll horizontally.

## Controls

| Control | Action |
| --- | --- |
| Up/Down | Move through the focused file list |
| Enter or click a file | Load its diff |
| Enter or click a commit | Expand its changed files |
| Space | Stage the focused unstaged file, or unstage the focused staged file |
| Click `[ ]` | Stage or unstage that file |
| Drag a divider | Resize the Changes sidebar or its sections |
| `r` | Refresh repository status and files |

Use the Changes and Files tabs (or Textual's normal tab navigation) to switch
between repository changes and the filesystem browser. Refresh reloads both.

## Current Scope

GitPane supports whole-file staging and unstaging, syntax-highlighted unified
diffs, and safe text-file previews up to 1 MiB in an accessible dark theme. It
does not yet support hunk or line staging, commits, conflict resolution,
renames, binary previews, or automatic file watching.
