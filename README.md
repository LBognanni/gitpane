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
changes lists also show renames and merge conflicts with an explanation; these
entries cannot be staged, unstaged, discarded, or previewed yet. The
**Files** tab shows tracked and non-ignored untracked files below the directory
where GitPane was launched; select one for a syntax-highlighted preview. Long
lines scroll horizontally.

## Controls

| Control | Action |
| --- | --- |
| Up/Down | Move through the focused file list |
| Enter or click a file | Load its diff |
| Enter or click a commit | Expand its changed files |
| `j` / `k` | Move the selection or scroll the focused viewer |
| `1` / `2` | Switch to the Changes / Files tab |
| `n` / `p` | Move to the next / previous change in a diff |
| Space or click `[ ]` | Check or uncheck the focused file for a bulk action |
| `s` | Stage or unstage the focused file |
| `d` | Discard the focused unstaged file after confirmation |
| Hover a file and click `↑` / `↓` | Stage or unstage that file |
| Hover an unstaged file and click `↶` | Discard its changes after confirmation |
| Section-header actions | Stage, unstage, or discard all checked files |
| Drag a divider | Resize the Changes sidebar or its sections |
| `r` | Refresh repository status and files |
| `w` | Toggle line wrapping in the active viewer |
| `h` | Show the keyboard shortcut popup |
| `q` | Quit GitPane |

Mouse controls are supported throughout the interface.

Use the Changes and Files tabs (or Textual's normal tab navigation) to switch
between repository changes and the filesystem browser. Refresh reloads both.

## Current Scope

GitPane supports whole-file staging, unstaging, and confirmed discarding; bulk
file actions; syntax-highlighted unified diffs; and safe text-file previews up
to 1 MiB in an accessible dark theme. It does not yet support hunk or line
staging, commits, conflict resolution, renames, binary previews, or automatic
file watching.
