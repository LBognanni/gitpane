# gitpane

A terminal Git status, history, diff, and file browser. It shows staged and
unstaged files, displays full-context unified diffs, previews repository files,
and can stage, unstage, or discard whole files.

## Requirements

- Git
- A [Nerd Font](https://www.nerdfonts.com/) configured in your terminal

Run GitPane from inside a Git repository.

## Install And Run

Install the latest release for Linux or macOS to `~/.local/bin`:

```bash
curl -fsSL https://github.com/LBognanni/gitpane/releases/latest/download/install.sh | sh
gitpane
```

Set `GITPANE_VERSION` to a release tag to install that release, or
`GITPANE_INSTALL_DIR` to install somewhere else, for example
`curl -fsSL ... | GITPANE_INSTALL_DIR="$HOME/bin" sh`.

To build from source instead:

```bash
cargo install --locked --git https://github.com/LBognanni/gitpane
```

Upgrading from the Python version: run `uv tool uninstall gitpane` first.

The **Changes** tab lists staged files, unstaged files, and up to 100 recent
commits from the current branch. Select a commit to expand its changed files,
then select a file to show its historical diff. The selected file is shown
above each viewer, and the current branch appears in the bottom status bar. The
changes lists also show renames and merge conflicts with an explanation; these
entries cannot be staged, unstaged, discarded, or diffed yet. The **Files** tab
shows tracked and non-ignored untracked files below the directory where
GitPane was launched, in a tree with its own draggable divider; select one for
a syntax-highlighted preview, or press `t` to jump to a file by name. Long
lines scroll horizontally.

## Controls

| Control | Action |
| --- | --- |
| Up/Down or `j` / `k` | Move the selection in the focused list or tree, or scroll the focused viewer |
| Left/Right | Collapse / expand the selected commit or folder, or scroll the focused viewer sideways |
| PageUp/PageDown, Home/End | Scroll the focused viewer by a page, or to the top / bottom |
| Tab / Shift+Tab | Move focus to the next / previous pane |
| Enter or click a file | Load its diff, or its preview in the Files tab |
| Enter or click a commit or folder | Expand or collapse it |
| `1` / `2` or click a tab | Switch to the Changes / Files tab |
| `n` / `p` or click `↓` / `↑` above the diff | Move to the next / previous change in a diff |
| `t` | Jump to a file by name (Files tab) |
| Space or click `[ ]` | Check or uncheck the focused file for a bulk action |
| `s` | Stage or unstage the focused file |
| `d` | Discard the focused unstaged file after confirmation |
| Hover a file and click `↑` / `↓` | Stage or unstage that file |
| Hover an unstaged file and click `↶` | Discard its changes after confirmation |
| Section-header `↑` / `↓` / `↶` | Stage, unstage, or discard all checked files |
| Drag a divider | Resize the Changes sidebar, its sections, or the Files tree |
| Drag across a viewer | Select text and copy it to the clipboard |
| Mouse wheel (Shift for sideways) | Scroll the list or viewer under the pointer |
| `r` | Manually refresh status, history and the Files tab |
| `w` | Toggle line wrapping in the active viewer |
| `h` | Show or close the keyboard shortcut popup |
| Esc | Close the open popup |
| `q` or Ctrl+C | Quit GitPane |

Mouse controls are supported throughout the interface.

Status and history update automatically as the repository changes. `r` remains
a manual full refresh; the Files tab is only refreshed by `r`, not on every
edit.

## Current Scope

GitPane supports whole-file staging, unstaging, and confirmed discarding; bulk
file actions; syntax-highlighted unified diffs; and safe UTF-8 text-file
previews up to 1 MiB in an accessible dark theme. It does not yet support hunk
or line staging, commits, conflict resolution, renames, or binary previews.

## Development

Run `cargo run` inside a Git repository. The quality gates are:

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

`.devcontainer/up.sh` starts a development container with the Rust toolchain.

## Releasing

Bump the version in `Cargo.toml`, commit, then tag `vX.Y.Z` and push the tag.
Every push to a branch other than `main` publishes a beta prerelease; install
one with:

```bash
curl -fsSL https://github.com/LBognanni/gitpane/releases/download/<tag>/install.sh | sh
```

Licensed under the GNU GPL v3; see `LICENSE`.
