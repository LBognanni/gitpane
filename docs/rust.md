# GitPane Rust rewrite

This file is the authoritative specification for rewriting GitPane in Rust. It
records the decisions taken during planning, the development environment, the
behavior the Rust version must reproduce, and ordered stories that follow the
process in `docs/workflow.md`.

The Python application in `gitpane/` stays in this worktree, unchanged, as the
behavioral reference until the cutover story (RS-S12). When this document and
the Python code disagree about existing behavior, the Python code wins unless
this document explicitly lists the difference as a decision.

## 1. Goal

Rewrite GitPane in Rust for performance, especially diff rendering and syntax
highlighting, while keeping the current workflow and appearance.

### In scope

- Parity with every control in the `README.md` controls table and every
  behavior covered by the Python test suite (see section 12).
- Deliberate improvements:
  - Removed lines are syntax highlighted (today they are plain text).
  - Full-file context is really full: `-U9999` drops context more than 9,999
    lines from a change.
  - The line-number gutter widens for files with more than 9,999 lines instead
    of misaligning.
  - The Files tab tree gets the same draggable splitter as the Changes sidebar.
  - Focused lists and trees show the focus border (the Python TCSS never shows
    it; see the `docs/milestones.md` completion notes).
  - Startup is effectively instant and the app ships as a single binary.

### Out of scope

The same as today: hunk or line staging, commits, conflict resolution, renames,
binary previews, and side-by-side diffs. Also out of scope: persisting pane
sizes between sessions, language injections (for example SQL inside strings),
and a plugin or configuration system.

## 2. Decisions record

| Decision | Choice | Why |
| --- | --- | --- |
| Language | Rust | Performance is the top priority. Rust has native tree-sitter bindings and proven TUI git clients (gitu, gitui). |
| Not Go | — | Bubble Tea v2 renders well, but Go highlighting is either chroma (a regex port of Pygments) or tree-sitter through cgo. |
| Not Zig | — | No mature TUI or highlighting ecosystem; the language is pre-1.0. |
| Not OpenTUI (TypeScript + Zig core) | — | Has a ready-made Diff component, but app code runs on a JS runtime and large-diff behavior is undocumented. |
| Not staying on Textual | — | The highlighting fix would work in Python too, but a rewrite also removes Python startup cost, per-frame overhead, and packaging friction. |
| TUI library | ratatui + crossterm, no widget framework | The layout is fixed (a few panes and three modals). A small in-house focus and hit-test layer is simpler than depending on rat-salsa (small adoption, one maintainer). |
| Highlighter | tree-sitter only | Parse the whole file natively on a worker, then query highlights only for visible rows. syntect must highlight top-down from line 1, which costs about a second to reach the bottom of a 50k-line file. |
| Language coverage | About 20 bundled grammars, plain text otherwise | Every grammar is a compiled crate; coverage is traded for speed and simplicity. |
| Git access | `git` CLI | Mirrors `gitpane/git.py`, respects user configuration, and keeps the adapter tests meaningful. |
| Diff cache | None | Parsing is cheap in Rust and highlighting is per viewport. An equal patch on quiet reload keeps the current document instead. |
| Tooltips | Shown in the status bar while hovering an icon button | Floating tooltips need timers and overlay placement; the status bar is simpler and still discoverable. |
| Clipboard | OSC 52 | Works in modern terminals and over SSH, with no system clipboard dependency. |
| Reference code | gitu (tree-sitter diff highlighting), gitui (ratatui git client) | Borrow ideas, not code wholesale; both have a different UX. |

## 3. Development environment

### 3.1 Worktree

- All Rust work, including this document, happens in the git worktree
  `.claude/worktrees/rust-rewrite` on branch `worktree-rust-rewrite`.
- The main checkout ignores nested worktrees through the local
  `.git/info/exclude` entry `.claude/worktrees/` (already added; not
  committed).
- The branch merges into `main` at cutover (RS-S12).

### 3.2 Devcontainer

The host has no Rust toolchain, so building, testing, and running Claude Code
all happen in a devcontainer. Docker is installed on the host; start it only
when working in the container.

The difficulty: a worktree's `.git` is a file containing an absolute path to
the main repository's `.git` directory
(`/home/loris/source/gitpane/.git/worktrees/rust-rewrite`). A normal
devcontainer only mounts the opened folder, so Git breaks inside the container.
The solution: mount the main repository root inside the container at the same
absolute path it has on the host, and use the worktree as the container's
workspace folder. Git then works identically on the host and in the container,
and container-built binaries run on the host from the same paths.

Files (all in the worktree):

| Path | Purpose |
| --- | --- |
| `.devcontainer/devcontainer.json` | Container definition |
| `.devcontainer/Dockerfile` | Toolchain image |
| `.devcontainer/post-create.sh` | SSH key and shell setup, run inside the container |
| `.devcontainer/up.sh` | Host-side launcher that computes the main repository root |
| `.gitignore` | Add `.devcontainer/.ssh/` |

`Dockerfile` requirements:

- `FROM mcr.microsoft.com/devcontainers/rust:1-bookworm` (stable Rust, cargo,
  clippy, rustfmt, git, curl, and a `vscode` user with UID 1000).
- `apt-get install` `build-essential` (tree-sitter grammars compile C and C++)
  and `ncurses-term` (terminfo entries for common SSH client terminals).
- Write `/etc/profile.d/rust.sh` exporting `RUSTUP_HOME=/usr/local/rustup`,
  `CARGO_HOME=/usr/local/cargo`, and `PATH=/usr/local/cargo/bin:$PATH`. SSH
  login shells do not inherit Docker `ENV`.
- As `vscode`, install Claude Code with the native installer
  (`curl -fsSL https://claude.ai/install.sh | bash`). It installs into
  `~/.local/bin`, which Debian's default `~/.profile` adds to `PATH`. No Node is
  needed. End the Dockerfile as `root` so the sshd feature can start.

`devcontainer.json` requirements:

```jsonc
{
  "name": "gitpane-rust",
  "build": { "dockerfile": "Dockerfile" },
  // up.sh passes the MAIN repository root as the workspace folder. Mount it at
  // its host path so the worktree's absolute .git pointer resolves.
  "workspaceMount": "source=${localWorkspaceFolder},target=${localWorkspaceFolder},type=bind",
  "workspaceFolder": "${localWorkspaceFolder}/.claude/worktrees/rust-rewrite",
  "remoteUser": "vscode",
  "features": {
    "ghcr.io/devcontainers/features/sshd:1": {}
  },
  // The devcontainer CLI ignores forwardPorts. Bind to loopback only.
  "appPort": ["127.0.0.1:2222:2222"],
  "mounts": [
    "source=${localEnv:HOME}/.claude,target=/home/vscode/.claude,type=bind",
    "source=gitpane-cargo-registry,target=/usr/local/cargo/registry,type=volume"
  ],
  "postCreateCommand": "bash .devcontainer/post-create.sh"
}
```

- Do not bind-mount `~/.claude.json` as a single file: atomic rewrites of a
  single-file bind mount fail. A one-time onboarding prompt inside the container
  is acceptable; the login itself is shared through `~/.claude`.
- The host's `~/.claude/settings.json` hooks run inside the container too. Hooks
  that call host-only paths may fail there; that is accepted.
- The project's subagents (`.claude/agents/coder.md`, `reviewer.md`,
  `senior-coder.md`) are tracked in the repository, so they are available inside.

`post-create.sh` requirements (runs inside the container, in the worktree):

1. If `.devcontainer/.ssh/id_ed25519` is missing, generate it with
   `ssh-keygen -q -t ed25519 -N '' -C gitpane-devcontainer`. The directory is
   gitignored, and the file appears on the host at the same path because of the
   identical-path mount. The host has no existing public key to reuse.
2. Install `.devcontainer/.ssh/id_ed25519.pub` as `~/.ssh/authorized_keys`
   (mode 600, directory mode 700).
3. Append to `~/.bashrc`: when `$SSH_CONNECTION` is set, `cd` into the
   workspace folder.
4. `git config --global --add safe.directory '*'`.

`up.sh` requirements (runs on the host):

```bash
#!/usr/bin/env bash
# Start the devcontainer with the main repository root as the workspace folder.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
common="$(git -C "$here" rev-parse --path-format=absolute --git-common-dir)"
exec npx -y @devcontainers/cli up \
  --workspace-folder "${common%/.git}" \
  --config "$here/devcontainer.json" "$@"
```

Host `~/.ssh/config` snippet (documented, not committed):

```
Host gitpane-dev
  HostName 127.0.0.1
  Port 2222
  User vscode
  IdentityFile /home/loris/source/gitpane/.claude/worktrees/rust-rewrite/.devcontainer/.ssh/id_ed25519
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR
```

Known-hosts checking is disabled because the container's host keys change on
every rebuild; the port is bound to loopback only.

### 3.3 Daily workflow

1. Start Docker on the host.
2. Run `.devcontainer/up.sh` from the worktree (it works from any directory).
   It is idempotent: it reuses an existing container.
3. Run `ssh gitpane-dev`. The shell starts in the worktree.
4. Run `claude` inside the container for the story workflow.
5. Alternative entry: VS Code, "Dev Containers: Attach to Running Container",
   then open the worktree folder. Do not use "Reopen in Container" on the
   worktree folder: it would mount only the worktree and break Git.

Smoke testing is owned by the user:

- Over SSH: `cargo run` in the worktree. Mouse, truecolor, and OSC 52 pass
  through to the host terminal and its Nerd Font.
- On the host: run `target/debug/gitpane` from the worktree path directly. It is
  the same absolute path, and a bookworm build runs on the newer host glibc.

## 4. Locked decisions

- Crate at the worktree root (`Cargo.toml`, `src/`) next to the Python
  `gitpane/` package. Package and binary are both named `gitpane`. Edition 2024.
  Commit `Cargo.lock`. Add `target/` to `.gitignore`.
- Dependencies (latest compatible versions, chosen in RS-S1 and later stories):

  | Crate | Use |
  | --- | --- |
  | `ratatui` | Rendering, layout, `TestBackend` |
  | `crossterm` | Terminal, input, mouse capture with motion events, OSC 52 (`osc52` feature, or a small manual escape) |
  | `tree-sitter` + grammar crates | Parsing and highlight queries (section 7) |
  | `notify-debouncer-full` | Filesystem watching |
  | `unicode-width` | Terminal cell widths |
  | `directories` | First-launch marker location |
  | `emojis` | Gitmoji shortcode expansion |
  | `tui-tree-widget` | Commit tree and Files tree |

  Add nothing else without recording the reason in the story report.
- No async runtime. Threads plus `std::sync::mpsc` channels.
- Paths are handled as UTF-8 `String`s. A status path that is not valid UTF-8 is
  listed as unsupported with the reason `Non-UTF-8 paths are not supported.`
- Unit and component tests live in `#[cfg(test)]` modules next to the code.
  Workflow tests live in `tests/*.rs` and coexist with the Python tests in
  `tests/` until cutover. Shared test support goes in `tests/common/mod.rs`
  only when at least two test files need it.
- Quality gates, run inside the container:

  ```bash
  cargo fmt --check
  cargo clippy --all-targets -- -D warnings
  cargo test
  ```

- Every coder prompt includes the Required Coder-Prompt Rules from
  `docs/workflow.md`. For this milestone "Do NOT boot the editor" means: **do not
  run the TUI binary interactively**; tests only.

## 5. Architecture

### 5.1 Modules

| Module | Responsibility |
| --- | --- |
| `main.rs` | Find the repository, claim first launch, set up and restore the terminal (including on panic), run the loop |
| `lib.rs` | Module declarations, so `tests/*.rs` can use the crate |
| `model.rs` | `Side`, `FileEntry`, `Commit`, `CommitFile`, `RepoState`, `DiffEntry` |
| `git.rs` | `Runner` trait, `GitApi` trait, `CliGit` implementation, porcelain parsers |
| `diff.rs` | Unified-diff parser, `Row`, `change_indices` |
| `highlight.rs` | Language registry, parsing, viewport-range highlight queries, capture palette |
| `document.rs` | Diff and preview documents: gutter text plus source lines with highlight lookups |
| `code_view.rs` | Virtual viewer state, rendering, scrolling, wrapping, selection |
| `layout.rs` | Splitter weights, `resize_pair`, pane rectangles |
| `app.rs` | `App` state, `Event`, `Effect`, `update()` |
| `runtime.rs` | Threads, git queue, effect execution, the main loop |
| `ui.rs` | `render()`: tabs, sidebar, lists, trees, viewers, modals, toasts, hit map |
| `watcher.rs` | `Invalidation`, `classify()`, watcher thread |
| `icons.rs` | Nerd Font tables ported from `gitpane/icons.py` |
| `theme.rs` | Color tokens and the syntax palette |

### 5.2 Event loop

- One `mpsc` channel carries every `Event`: terminal input (from an input
  thread), worker results, and watcher messages.
- Main loop: block on `recv` (with a timeout for the next toast expiry), drain
  any queued events with `try_recv`, apply each through `App::update`, execute
  the returned effects, then draw **once**. Draining before drawing coalesces
  bursts such as mouse motion.
- `App::update(&mut self, event: Event) -> Vec<Effect>` is the only place state
  changes. It never blocks and never calls Git.
- `ui::render(&mut App, &mut Frame)` draws and records a hit map: an ordered
  list of `(Rect, Target)` for panes, rows, buttons, splitters, scrollbars, and
  modal controls. Mouse events are routed to the last (topmost) target that
  contains the pointer, using the hit map from the previous draw.

### 5.3 Background work

- **Git queue:** one thread processes status reads and mutations strictly in
  FIFO order. A mutation job performs the mutation and then its own status read
  in the same job, so no other status read can interleave (see section 11).
- **Latest-only workers:** one thread each for diff loads, history, commit
  files, the file list, and previews. Each worker drains its request channel to
  the newest request before starting, so rapid navigation never piles up work.
- Every request carries a token. The UI drops results whose token is no longer
  current. Workers are never cancelled; stale results are simply ignored.
- Quitting never waits for in-flight work.

### 5.4 Git adapter boundary

```rust
pub trait Runner: Send + Sync {
    /// Run `git --literal-pathspecs <args>` in `cwd` with GIT_OPTIONAL_LOCKS=0.
    fn run(&self, cwd: &Path, args: &[&str], allowed_codes: &[i32]) -> Result<String, GitError>;
}

pub trait GitApi: Send + Sync {
    fn status(&self, root: &Path) -> Result<RepoState, GitError>;
    fn files(&self, cwd: &Path) -> Result<Vec<String>, GitError>;
    fn commits(&self, root: &Path) -> Result<Vec<Commit>, GitError>;
    fn commit_files(&self, root: &Path, commit: &Commit) -> Result<Vec<CommitFile>, GitError>;
    fn diff(&self, root: &Path, entry: &DiffEntry) -> Result<String, GitError>;
    fn stage(&self, root: &Path, paths: &[&str]) -> Result<(), GitError>;
    fn unstage(&self, root: &Path, paths: &[&str]) -> Result<(), GitError>;
    fn restore(&self, root: &Path, paths: &[&str]) -> Result<(), GitError>;
    fn clean(&self, root: &Path, paths: &[&str]) -> Result<(), GitError>;
    fn git_dirs(&self, root: &Path) -> Result<(PathBuf, PathBuf), GitError>;
}
```

`CliGit<R: Runner>` implements `GitApi`. Adapter tests use a recording `Runner`
and assert argv and parsed results. Application tests use a `FakeGit`
implementing `GitApi` with realistic data.

## 6. Git adapter

Port `gitpane/git.py` exactly. Every command runs as
`git --literal-pathspecs …` in the given directory with the inherited
environment plus `GIT_OPTIONAL_LOCKS=0`. Output is decoded as UTF-8. An exit
code outside the allowed set (default `[0]`) is an error. The user-facing error
text is Git's trimmed stderr when non-empty, otherwise the error's own text.

| Operation | Command | Notes |
| --- | --- | --- |
| Repository root | `rev-parse --show-toplevel` | Run in the launch directory |
| Git directories | `rev-parse --path-format=absolute --git-dir --git-common-dir` | Two lines: worktree-specific, then common |
| Status | `status --porcelain=v2 --branch -z --untracked-files=all` | Parsing below |
| Files | `ls-files -z --cached --others --exclude-standard -- .` | Run in the launch directory; sorted; empty entries dropped |
| HEAD check | `rev-parse --verify --quiet HEAD` | Allowed codes 0 and 1; empty output means an unborn branch |
| Commits | `log --max-count=100 -z --format=%H%x00%h%x00%P%x00%s` | Skipped entirely on an unborn branch; four NUL fields per commit; parent is the first of `%P` |
| Commit files (root commit) | `diff-tree --root --no-commit-id --name-status --no-renames -r -z <hash>` | Status/path pairs; status is the first character |
| Commit files | `diff --name-status --no-renames -z <parent> <hash>` | Same parsing |
| Historical diff (root commit) | `show --format= -U<N> --no-color --no-ext-diff <hash> -- <path>` | |
| Historical diff | `diff -U<N> --no-color --no-ext-diff <parent> <hash> -- <path>` | |
| Staged diff | `diff --cached -U<N> --no-color --no-ext-diff -- <path>` | |
| Untracked diff | `diff --no-index -U<N> --no-color --no-ext-diff -- /dev/null <path>` | Allowed codes 0 and 1 |
| Unstaged diff | `diff -U<N> --no-color --no-ext-diff -- <path>` | |
| Stage | `add -- <paths…>` | |
| Unstage | `restore --staged -- <paths…>`, or `rm --cached -f -- <paths…>` on an unborn branch | |
| Discard tracked | `restore --worktree -- <paths…>` | |
| Discard untracked | `clean -f -- <paths…>` | |

`<N>` is `1000000` instead of `9999`, so context covers the whole file.

Porcelain v2 status parsing (from `_parse_status`):

- `# branch.head <name>` gives the branch; `# branch.oid <oid>` gives the
  commit. A head of `(detached)` with an oid becomes `detached at <first 7>`.
- `1 <XY> … <path>` (9 fields): for X (staged) and Y (unstaged), codes `A`, `M`,
  `D` produce an entry with that status; `T` produces `M`; others are skipped.
- `? <path>`: an unstaged entry with status `?`.
- `2 <XY> … <score> <path>` (10 fields) followed by a separate NUL record with
  the original path: each non-`.` side produces an unsupported entry with reason
  `Rename from <orig> is not supported.` or, when the score starts with `C`,
  `Copy from <orig> is not supported.`
- `u <XY> … <path>` (11 fields): one unstaged entry with status `U` and reason
  `Conflict (<XY>) resolution is not supported.`
- Malformed records are skipped.

## 7. Diff and highlighting pipeline

### 7.1 Parser

Replace `unidiff` with our own parser in `diff.rs` that keeps the Python
semantics (`gitpane/diff.py`):

- `Row { old_no: Option<u32>, new_no: Option<u32>, text: String, kind: Context | Add | Remove }`.
- Hunks from all files in the patch are flattened in order.
- `\r\n` and `\n` line endings are removed; all other whitespace is preserved.
- `\ No newline at end of file` markers are not rows.
- `change_indices(rows)` returns the first row of each contiguous block of
  added or removed rows. `first_change` is the first of those.

### 7.2 Sides

- The **new side** is the text of rows with a `new_no` (context and added), in
  order. The **old side** is the text of rows with an `old_no` (context and
  removed).
- A worker thread parses each non-empty side with the language's tree-sitter
  parser and keeps each side's source, the byte offset of each line start, and
  the syntax tree.
- Rows with a `new_no` take their colors from the new side; removed rows take
  theirs from the old side.

### 7.3 Viewport highlighting

- At render time, for each visible row, run the language's highlights query
  with a `QueryCursor` limited (`set_byte_range`) to that line's bytes.
  Highlighting work is therefore bounded by the viewport, not the document.
  No per-line cache at first. Add one only if a later story shows a need.
- Precedence when captures overlap: paint outer ranges before inner ranges, so
  the innermost range wins. For identical ranges, the capture from the pattern
  with the lowest index wins (tree-sitter-highlight's convention, which the
  bundled query files are written for).
- Text predicates (`#match?`, `#eq?`) are honored by the binding. Property
  predicates such as `#is-not? local` are ignored. No injections, no locals.
- A capture name maps to a palette color by the longest matching dotted prefix
  (for example `function.method` falls back to `function`). Unknown captures use
  the default foreground.

### 7.4 Language registry

| Language | Detection | Crate |
| --- | --- | --- |
| Python | `.py`, `.pyi`, shebang `python` | `tree-sitter-python` |
| Rust | `.rs` | `tree-sitter-rust` |
| Go | `.go` | `tree-sitter-go` |
| C | `.c`, `.h` | `tree-sitter-c` |
| C++ | `.cc`, `.cpp`, `.cxx`, `.hpp`, `.hh`, `.hxx` | `tree-sitter-cpp` (query: C + C++) |
| C# | `.cs` | `tree-sitter-c-sharp` |
| Java | `.java` | `tree-sitter-java` |
| JavaScript | `.js`, `.mjs`, `.cjs`, `.jsx`, shebang `node` | `tree-sitter-javascript` (+ JSX query for `.jsx`) |
| TypeScript / TSX | `.ts`, `.mts`, `.cts` / `.tsx` | `tree-sitter-typescript` (query: JavaScript + TypeScript; TSX adds JSX) |
| Ruby | `.rb`, `Gemfile`, `Rakefile`, shebang `ruby` | `tree-sitter-ruby` |
| PHP | `.php` | `tree-sitter-php` |
| Bash | `.sh`, `.bash`, `.zsh`, `.bashrc`, `.zshrc`, `.profile`, `PKGBUILD`, shebang `sh`/`bash`/`zsh` | `tree-sitter-bash` |
| HTML | `.html`, `.htm` | `tree-sitter-html` |
| CSS | `.css` | `tree-sitter-css` |
| JSON | `.json`, `.jsonc` | `tree-sitter-json` |
| TOML | `.toml`, `Cargo.lock`, `uv.lock` | `tree-sitter-toml-ng` |
| YAML | `.yaml`, `.yml` | `tree-sitter-yaml` |
| Markdown | `.md`, `.markdown` | `tree-sitter-md` (block grammar only) |
| SQL | `.sql` | `tree-sitter-sequel` |
| Lua | `.lua` | `tree-sitter-lua` |

- Detection order: exact file name (case-insensitive), then extension
  (case-insensitive), then a `#!` first line. Anything else is plain text,
  styled with the default foreground.
- Use each crate's bundled highlight query constants, concatenated where the
  upstream convention requires (noted above).
- If a crate is incompatible with the chosen `tree-sitter` version or ships no
  highlight query, drop that language (plain text) and say so in the story
  report. Do not vendor grammars or queries.

### 7.5 Syntax palette

The viewer background is the monokai background `#272822`, as today (Rich's
default `monokai` theme). Palette:

| Capture prefix | Color |
| --- | --- |
| `comment` | `#75715e` |
| `string`, `character` | `#e6db74` |
| `escape`, `number`, `float`, `boolean`, `constant` | `#ae81ff` |
| `keyword`, `type`, `storage` | `#66d9ef` |
| `keyword.import`, `include`, `operator`, `tag`, `keyword.operator` | `#f92672` |
| `function`, `method`, `constructor`, `attribute`, `decorator` | `#a6e22e` |
| `variable.parameter`, `parameter`, `variable.builtin` | `#fd971f` |
| everything else | `#f8f8f2` |

Tests never assert these values; they assert that highlighted source differs
from plain text and that gutters stay uncolored (section 12).

### 7.6 Diff document rows

- Gutter: `"{marker} {old:>W} {new:>W} "`, where the marker is `+`, `-`, or a
  space; missing numbers are blank; `W` is `max(4, digits of the largest line
  number in the document)`.
- Added rows have the addition background (`#142b1d`) across the full row
  width; removed rows have the removal background (`#351b20`). Syntax colors
  apply only to the source text, never to the gutter.
- Source text is shown literally; there is no markup interpretation.
- An unsupported entry's document is its reason as a single plain row.

### 7.7 Preview documents

Ported from `gitpane/preview.py`:

- `lstat` first. Not a regular file: `Only regular files can be previewed.`
- Larger than 1 MiB (1,048,576 bytes), checked from the metadata and again after
  reading at most 1 MiB + 1 byte: `File is too large to preview (maximum 1 MiB).`
- Missing: `File is no longer available.` Other I/O errors:
  `File could not be read.`
- Contains a NUL byte: `Binary files cannot be previewed.`
- Invalid UTF-8: `File is not valid UTF-8.`
- Otherwise normalize `\r\n` and `\r` to `\n` and highlight the whole file as
  one side. Lines keep a trailing empty line when the file ends with a newline,
  matching Python's `source.count("\n") + 1` rule.
- Each row gets a dim gutter `" {n:>W} "` (`W` = digits of the line count), and
  the document's wrap indent is `W + 2`.

## 8. CodeView

One component serves both the diff and preview viewers. Port the behavior of
`gitpane/widgets/code_view.py`:

- **Virtual rendering:** only visible rows are materialized, highlighted, and
  drawn.
- **Display text:** tabs expand to 8-column stops across the whole row
  (gutter plus source). Cropping and horizontal scrolling use terminal cell
  widths (`unicode-width`), so wide characters are never split.
- **Unwrapped mode:** horizontal scroll range is the widest row. Both
  scrollbars appear when content overflows.
- **Wrapped mode:**
  - Rows wrap at word boundaries and fold words longer than the width.
    Continuation rows are indented by the document's wrap indent (clamped to
    `width - 1`) and never render as gutter-only rows.
  - The visual-row index is rebuilt when the width changes.
  - Horizontal scroll is 0 and the horizontal scrollbar is hidden.
  - Toggling wrap keeps relative vertical progress
    (`scroll_y / max_scroll_y`) and resets horizontal scroll.
  - Resizing while wrapped keeps the same source position at the top of the
    viewport.
- **Keys** (when the viewer is focused): Up/Down and `j`/`k` scroll one row;
  Left/Right scroll one column; PageUp/PageDown move one viewport height
  without animation; Home/End jump to the top or bottom. All movement clamps to
  the document bounds.
- **Mouse wheel:** scrolls three rows vertically. Shift+wheel, or horizontal
  wheel events, scroll horizontally.
- **Jump scrollbar:** clicking the vertical track jumps using
  `scrollbar_click_target`. A click on the first cell goes to the top, a click
  on the last cell goes to the bottom, and anything else centers the document
  on `(y + 0.5) / height * virtual_size - window / 2`, clamped. Dragging the
  thumb scrolls proportionally.
- **Selection:**
  - Dragging with the left button selects text. The selection is stored as
    (source row, character offset) pairs in the displayed, tab-expanded row
    text (including the gutter).
  - The selection background is `$focused-selection` and keeps each cell's
    foreground color.
  - On release, a non-empty selection is copied with OSC 52. Wrapped rows copy
    as their source text, without visual newlines.
  - A selection ending past the last row extends to the end of the last row;
    a trailing blank line is preserved.
  - Replacing the document clears the selection. Resizing keeps it.
- **Document replacement** resets scroll to (0, 0) unless the caller restores a
  position (quiet reload, section 11).
- **Scroll requests:** a request to scroll to a source row, made before the
  first draw, is resolved during the next draw, when the viewport and wrap
  width are known.

## 9. Resizable layout

Resizing is a first-class feature and has its own story (RS-S6).

### 9.1 Splitters

| Tab | Splitter | Separates | Minimum |
| --- | --- | --- | --- |
| Changes | Vertical | Sidebar and diff pane | 15 columns on each side |
| Changes | Horizontal | Staged section and Unstaged section | 3 rows per section |
| Changes | Horizontal | Unstaged section and Commits section | 3 rows per section |
| Files | Vertical | Files tree and preview pane (new) | 15 columns on each side |

### 9.2 Sizing rules

Ported from `gitpane/widgets/splitter.py`:

- Initial sizes: the sidebar and the Files tree are 30 columns; the diff and
  preview panes take the rest; the three sidebar sections are equal thirds.
- `resize_pair(first, second, delta, minimum)` keeps `first + second` constant
  and clamps each side to at least `minimum`. For example,
  `(30, 70, 10, 15) → (40, 60)`, `(30, 70, -100, 15) → (15, 85)`, and
  `(3, 3, 0, 3) → (3, 3)`.
- At drag start, every pane in that group is frozen at its current size, and
  the sizes become proportional weights. Only the two panes adjacent to the
  dragged splitter change. Dragging the first sidebar splitter leaves the
  Commits section's weight unchanged.
- After a drag, a terminal resize scales the panes by their weights. Before any
  drag, the 30-column sidebar and Files tree stay fixed.
- When the terminal is too small for every minimum, sizes shrink in proportion.
  The layout never panics, never produces negative sizes, and keeps every pane
  at least one cell wherever possible.

### 9.3 Interaction and appearance

- A vertical splitter draws `│` down its full height; a horizontal splitter
  draws `─` across its full width, in the `$border` color. While hovered, and
  for the whole drag, it uses the `$accent` color.
- Pressing the left button on a splitter starts a drag. Motion events resize
  the panes, and releasing the button ends the drag. The drag continues even if
  the pointer leaves the splitter cell.
- Dragging a splitter never starts a text selection.

### 9.4 Required outcomes

- Dragging the sidebar splitter right by five columns grows the sidebar by five
  columns, shrinks the diff pane by five, and keeps their total.
- Minimums clamp in both directions.
- Dragging the first sidebar splitter keeps the Commits section's height.
- After a drag, resizing the terminal to 140×40, 80×24, and 60×20 keeps the
  proportions within rounding. The sidebar stays at least 15 columns, the diff
  pane at least 10, and every list at least 3 rows. The diff viewer can still
  scroll in both directions, and wrapping still works.
- The Files splitter resizes the tree and the preview the same way.
- A hovered or dragged splitter renders differently from an idle one. Tests
  assert the difference, not a color value.

## 10. UI specification

### 10.1 Layout

```
 Changes  Files                                              ← tabs
 Staged                         ↓│ src/app.py            ↑ ↓   ← title rows
┌──────────────────────────────┐ │   12   12 def main():        ← diff view
│[ ] M src/app.py              │ │ -   13      old()
└──────────────────────────────┘ │ +        13 new()
───────────────────────────────── (splitter)
 Unstaged                     ↑ ↶│
┌──────────────────────────────┐ │
│[ ] ? notes.txt               │ │
└──────────────────────────────┘ │
─────────────────────────────────
 Commits                         │
┌──────────────────────────────┐ │
│▸ ✨ add thing abc1234        │ │
└──────────────────────────────┘ │
 Branch: main                                               ← status bar
```

- **Tabs row:** `Changes` and `Files`. Clicking a tab switches to it, as do `1`
  and `2`. The active tab is bold on `$raised-surface`; inactive tabs use
  `$muted-text` on `$surface`.
- **Changes tab:** the sidebar, a vertical splitter, and the diff pane.
  - The sidebar holds three sections (`Staged`, `Unstaged`, `Commits`)
    separated by horizontal splitters.
  - Each section has a one-row title bar and a bordered list or tree below it.
  - The border is `$border`, or `$focus` when the list or tree has focus.
- **Diff pane:** a title row showing the entry path on the left (truncated to
  one row) and the `↑` and `↓` change buttons right-aligned, followed by the
  CodeView.
- **Files tab:** the Files tree, a vertical splitter, and the preview pane. The
  preview pane has a title row with the path relative to the repository root,
  followed by a CodeView.
- **Status bar:** the bottom row shows `Branch: <branch>`, or the hint for a
  hovered icon button (see 10.4).

### 10.2 Status lists

- Row label: `[ ] <status> <path>`, or `[x] …` when checked. An unsupported row
  is `[!] <status> <path> - <reason>`. Rows are one line high and never wrap.
- Keys when a list has focus: Up/Down and `j`/`k` move the highlight; Enter
  selects, which loads the row's diff. Moving the highlight alone never loads a
  diff.
- Clicking a row highlights and selects it. Clicking columns 0–2 of a
  supported row toggles its checkbox instead. Space toggles the highlighted
  row. Unsupported rows cannot be checked.
- **Row actions:**
  - Shown for supported rows while the row is hovered, or while it is
    highlighted in the focused list.
  - Drawn over the right end of the row, three cells each: `↑` (stage;
    unstaged rows), `↓` (unstage; staged rows), and `↶` (discard; unstaged rows
    only).
  - Clicking an action applies it to that row alone.
- **Bulk actions:** these appear in a section's title bar only while at least
  one row in that list is checked. Staged has `↓` (unstage the checked rows).
  Unstaged has `↑` (stage the checked rows) and `↶` (discard the checked rows,
  after confirmation).
- **Row states:** the hovered row uses `$raised-surface`. The highlighted row
  uses `$inactive-selection`, or bold `$focused-selection` when its list has
  focus. Revealed actions must stay readable, with at least 4.5:1 contrast in
  every row state.

### 10.3 Commit tree

- The root is hidden. Each commit node is labeled with its subject, gitmoji
  shortcodes (`:bug:`) expanded to emoji, followed by a space and the short
  hash in dim text.
- Expanding a commit with no loaded children loads its files, showing a loading
  state on the tree. The results become leaves labeled `<status> <path>`, or a
  single inert `(no changed files)` leaf.
- Selecting a file leaf loads its historical diff into the shared diff pane.
- The cursor row is bold on `$focused-selection`.
- Keys: Up/Down and `j`/`k` move; Enter toggles a commit or selects a file;
  Right and Left expand and collapse. Clicking a node selects it and toggles
  commits.

### 10.4 Buttons and hints

Icon buttons are three cells wide. Disabled buttons are dimmed and ignore
clicks. Hovering a button shows its hint in the status bar instead of the
branch:

| Button | Hint |
| --- | --- |
| Row `↑` / `↓` / `↶` | `Stage Changes` / `Unstage Changes` / `Discard Changes` |
| Bulk `↑` / `↓` / `↶` | `Stage Selected Changes` / `Unstage Selected Changes` / `Discard Selected Changes` |
| Diff `↑` / `↓` | `Previous Change` / `Next Change` |

Buttons are mouse targets; every button action also has a key. Tab and
Shift+Tab move focus between panes, not buttons.

### 10.5 Diff pane behavior

Ported from `gitpane/widgets/diff_pane.py`:

- **Request** (a row or file leaf is selected):
  - Set the title to the path, clear the change index, disable both change
    buttons, and increment the diff token.
  - An unsupported entry shows its reason immediately.
  - Anything else shows the loading state and starts a load.
- **Apply:**
  - Replace the document and set the change index to 0 (or none when there
    are no changes).
  - Scroll to (0, 0), then, if there is a change, to source row
    `max(0, change_row - 4)`.
  - Update the change buttons: `↑` is disabled at the first change and `↓` at
    the last.
- **`n` / `p` and the buttons:** move to the next or previous change, clamped
  to the list of changes, and scroll there. Only the Changes tab responds.
- **`w`:** toggles wrapping for the active tab's viewer only. The diff and
  preview wrap settings are independent and persist across document loads.
- **Invalidate** (manual status refresh): clear the selection, title,
  document, and change buttons, and drop any pending load.
- **Errors:**
  - A failed normal load clears the loading state and shows the error toast
    `Could not load diff`.
  - Quiet reload failures are covered in section 11.

### 10.6 Files tab

Ported from `gitpane/widgets/file_browser.py`:

- **Tree:**
  - The root is the launch directory's absolute path with an open folder icon,
    always expanded.
  - The tree is built from `files()`, which lists paths relative to the launch
    directory.
  - Within each directory, subdirectories come first, then files, each in
    sorted order.
  - Folders show closed or open icons as they are collapsed or expanded. Files
    get icons by exact name, then by extension (`gitpane/icons.py`, ported
    verbatim).
  - The icon glyph alone takes the icon's color; the name uses the normal
    text color.
- **Selecting a file** loads its preview. The title shows the path relative to
  the repository root. Selecting a directory toggles it.
- **Refresh** (`r`, and at startup):
  - Close the file jump dialog if it is open.
  - Reload the tree with a loading state.
  - Clear the preview title and document, and drop pending previews.
- **`t`** (Files tab only, ignored while the tree is loading) opens the file
  jump dialog. Choosing a file expands its ancestors, selects it (which loads
  the preview), scrolls it into view, and focuses the tree.

### 10.7 Modals

A modal dims the screen behind it (`$canvas` at 70%) and captures all input.

- **Discard confirmation:**
  - A 60-column dialog (at most 90% of the width) on `$raised-surface` with a
    `$border` border.
  - Title: `Discard Changes?`
  - Message:
    `Discard changes to <n> <file|files>? This cannot be undone.` When any
    entry is untracked, add ` Untracked files will be permanently deleted.`
  - Buttons: `Cancel` (focused initially) and `Discard` (error styled).
    Left/Right or Tab move between them, Enter activates, and Esc cancels.
- **Shortcuts:**
  - A 60-column dialog titled `Keyboard Shortcuts`, with the text of
    `gitpane/screens/shortcuts.py` verbatim and a focused `Close` button.
  - Esc, `h`, Enter, or clicking Close closes it.
- **File jump:**
  - A 70-column dialog anchored three rows from the top, with a one-line input
    whose placeholder is `Jump to file`.
  - The input supports typing and Backspace.
  - Queries shorter than three characters show no results.
  - Otherwise, the first 100 paths containing the query (case-insensitive)
    are listed, and `Showing first 100 matches` appears under the list when
    more exist.
  - Down moves from the input into the results. Enter picks the highlighted
    result, or the first one from the input.
  - Esc, or a click outside the dialog, cancels.
- **First launch:**
  - Show the shortcuts dialog once per user.
  - The marker file is `shortcuts-shown` in the gitpane state directory
    (`directories`: `state_dir()`, falling back to `data_local_dir()`).
  - Creating the marker exclusively claims the first launch. If the marker
    already exists, don't show the dialog. On any other error (for example, a
    read-only home directory), show it.

### 10.8 Keys

| Key | Action |
| --- | --- |
| `q`, Ctrl+C | Quit |
| `h` | Show or close the shortcuts dialog |
| `1` | Changes tab; focus Staged if non-empty, else Unstaged if non-empty, else Commits |
| `2` | Files tab; focus the Files tree |
| `j` / `k`, Down / Up | Move the focused list or tree, or scroll the focused viewer |
| Enter | Select or open the focused item |
| `n` / `p` | Next or previous change (Changes tab) |
| Space | Toggle the checkbox on the highlighted row |
| `s` | Stage or unstage the highlighted row of the focused list (supported rows) |
| `d` | Discard the highlighted unstaged row, after confirmation |
| `r` | Manual refresh: status, history, and files |
| `w` | Toggle wrapping in the active tab's viewer |
| `t` | File jump (Files tab) |
| Tab / Shift+Tab | Move focus between the panes of the active tab: Staged → Unstaged → Commits → diff viewer, or Files tree → preview |
| PageUp / PageDown, Home / End, Left / Right | Viewer navigation (section 8) |
| Esc | Close the active modal |

Clicking a pane focuses it.

### 10.9 Notifications and loading

- **Toasts:**
  - Stacked at the bottom right, up to 50 columns wide, wrapping their text.
  - Dismissed after five seconds or on click.
  - Errors have a title and red styling. Warnings have yellow styling.
- **Error toasts:** title `Could not <action>`, body is the Git error text. The
  actions are `refresh status`, `refresh history`, `load commit files`,
  `load diff`, `refresh files`, `stage`, `unstage`, and `discard changes`.
- **Loading:** a list, tree, or viewer that is loading shows a dim `Loading…`
  in place of its content. Quiet reloads never show a loading state.

### 10.10 Theme tokens

Port the tokens from `gitpane/app.tcss`:

| Token | Value |
| --- | --- |
| `canvas` | `#0d1117` |
| `surface` | `#161b22` |
| `raised-surface` | `#21262d` |
| `inactive-selection` | `#30363d` |
| `text` | `#f0f3f6` |
| `muted-text` | `#b1bac4` |
| `border` | `#6e7681` |
| `accent` | `#58a6ff` |
| `focus` | `#f2cc60` |
| `focused-selection` | `#174ea6` |
| `addition-background` | `#142b1d` |
| `removal-background` | `#351b20` |
| `diff-background` | `#272822` |
| `danger` | `#ff7b72` (discard buttons on hover) |

Panel titles, viewer titles, and the status bar are bold `muted-text` on
`raised-surface`. Scrollbars use `accent`.

## 11. Refresh and concurrency rules

Ported from `gitpane/app.py`, `gitpane/widgets/diff_pane.py`, and
`gitpane/watcher.py`. Tests assert the visible outcome of each rule.

### 11.1 Status

- The UI holds a current status token.
- **Manual status refresh** (startup, `r`, after a mutation):
  - Increment the token and show loading on both lists.
  - Drop pending diff loads without clearing the diff.
  - Queue a status read.
  - A result whose token is still current is applied fully: rebuild both lists,
    invalidate the diff pane, update the branch, and focus the first entry
    (Staged row 0, else Unstaged row 0). Otherwise it is dropped.
  - A failure clears both loading states and the diff loading state, and shows
    `Could not refresh status`.
- **Mutations** (stage, unstage, discard):
  - Unsupported entries are filtered out; nothing happens if none remain.
  - The UI starts a manual status refresh and queues one job that runs the
    mutation followed by its own status read.
  - A mutation failure shows `Could not <action>`, and the status read still
    happens.
  - Discard runs `restore` for tracked entries and `clean` for untracked ones.
  - Jobs run in request order, and no other status read can interleave with
    a mutation job.

### 11.2 Automatic refresh

- The watcher sends `Invalidation { status, history, changed_paths,
  index_changed }`.
- Invalidations without `status` are ignored. Others are merged into a single
  pending invalidation.
- If no automatic read is in flight, the pending invalidation is taken and
  read with the **current** token. An automatic read never increments the
  token, so it never supersedes a manual refresh.
- **When an automatic result arrives:**
  - **Stale token:** merge its invalidation back into pending and start another
    read.
  - **Failure:**
    - Merge its invalidation back into pending.
    - Warn once for the streak:
      `Automatic refresh failed: <reason>. Press r to refresh manually.`
    - Do not retry until the next watcher event.
  - **Success:**
    - End the status failure streak.
    - Apply quietly (below).
    - If more invalidations arrived during the read, start one follow-up read
      covering all of them, so a burst becomes a single follow-up.
- **Quiet apply:**
  - If the new state differs from the last applied state, rebuild the lists,
    keeping each list's highlighted row and checked rows by (side, path).
  - Never move focus, select a first entry, or show a loading state.
  - Reconcile the open diff (11.3).
  - If `history` was set, start a quiet history refresh.
- Equal states leave the lists, highlight, checks, and focus untouched. The
  open diff is still reconciled (11.3), so editing the selected file again
  reloads only its diff.

### 11.3 Open diff reconciliation (quiet apply only)

This applies only when the diff pane shows a working-tree entry (not a commit
file).

- If the entry is no longer present on its side:
  - Drop the selection and clear the pane.
  - Show the single row `The selected change is no longer present.`
  - Do not select a replacement.
- A **staged** entry is stale when `index_changed` or `history` is set.
- An **unstaged** entry is stale when its path is in `changed_paths`, or
  `history` is set, or `index_changed` is set and the entry is tracked (not
  `?`).
- **A stale entry is reloaded quietly:**
  - No loading state.
  - A result equal to the current patch leaves the document untouched.
  - Otherwise replace the document, keep the scroll position clamped to the new
    bounds, keep the wrap setting, and keep the change index if still valid
    (else reset to 0 or none).
  - A quiet failure keeps the old document and scroll, and warns once per diff
    failure streak. A quiet success ends that streak.
- A quiet reload that supersedes a normal request clears the loading state.
  Late results from older requests never replace newer ones.

### 11.4 History

- **Manual history refresh** (startup, `r`): show loading on the tree, then
  load.
- **Quiet refresh** (from automatic refresh): no loading state. A failure warns
  once per history failure streak and keeps the last tree.
- Only the newest request applies.
- When the commits equal the last applied list, keep the tree exactly: its
  expanded commits, loaded files, and cursor.
- **When the commits differ:**
  - Rebuild the tree collapsed, and drop pending commit-file loads.
  - Put the cursor back on the commit (or the parent commit of the file) it
    was on, by hash, and scroll it into view.
  - On a non-quiet refresh where both lists are empty and there are commits,
    select the first commit and focus the tree.

### 11.5 Files and previews

- File list loads and preview loads each have their own token. Only the newest
  of each applies.
- A preview that finishes after the tree was refreshed is dropped.

### 11.6 Watcher

Ported from `gitpane/watcher.py`:

- Before watching, call `git_dirs()`. Watch the worktree root recursively,
  plus the git directory and common directory when they are outside the root.
  Debounce: 250 ms.
- Classify every changed absolute path:
  - `<git dir>/index`: status and `index_changed`.
  - `<git dir>/HEAD`: status and history.
  - Under the common directory, `packed-refs` or anything under `refs/`:
    status and history. Any other path under the common directory is ignored.
  - `<root>/.git` itself (the file of a linked worktree) is ignored.
  - Any other path under the root: status, with the path relative to the
    root added to `changed_paths`.
  - Paths outside the repository are ignored.
- **Watcher lifecycle:**
  - The watcher reports `Started` once watching succeeds.
  - A setup failure shows the warning
    `Automatic refresh could not start. Press r to refresh manually.`
  - Any later error, or the watcher ending while the app runs, shows
    `Automatic refresh stopped. Press r to refresh manually.`
  - Each warning is shown once, and manual refresh keeps working.

## 12. Testing strategy

Follow `AGENTS.md`: test observable outcomes at the narrowest stable boundary,
use Git fakes in application tests, and never assert literal colors.

- **Adapter tests** (`src/git.rs`) use a recording `Runner`. They assert argv,
  working directory, the environment override, allowed exit codes, parsed
  results, and error text. No real repositories.
- **Parser tests** (`src/diff.rs`, `src/watcher.rs`, `src/layout.rs`,
  `src/icons.rs`) assert returned values.
- **Component tests:** `CodeView` and document rendering render into
  `ratatui::backend::TestBackend` buffers and assert visible text, cell
  presence of styles (for example, "keyword cells differ from plain cells",
  "gutter cells carry no syntax color", "selection background keeps
  foreground"), scroll bounds, and copied text. Copied text is captured through
  a clipboard effect, not a real terminal.
- **Workflow tests** (`tests/*.rs`) drive `App::update` with key, mouse, and
  resize events. A harness executes effects synchronously against a `FakeGit`,
  or holds chosen results so tests control completion order. Tests assert the
  rendered buffer, focus, enabled buttons, toasts, copied text, and `FakeGit`
  calls.
- **One explicit performance contract:** for a fixed viewport, the rows
  materialized per draw are bounded by the viewport height, whether the
  document has 100 rows or 100,000. Assert it through a render counter exposed
  for tests. There are no timing assertions.
- Tests never read private visual-row arrays, token values, or thread
  internals.

Python-to-Rust mapping:

| Python module | Rust location | Story |
| --- | --- | --- |
| `tests/test_git.py` | `src/git.rs` tests | RS-S2 |
| `tests/test_diff.py` | `src/diff.rs` tests | RS-S3 |
| `tests/test_diff_rendering.py` | `src/highlight.rs`, `src/document.rs` tests | RS-S3 |
| `tests/test_code_view.py` | `src/code_view.rs` tests | RS-S4 |
| `tests/test_theme.py` | `tests/theme.rs` | RS-S5 (grows through RS-S10) |
| `tests/test_splitter.py` | `src/layout.rs` tests, `tests/resize.rs` | RS-S6 |
| `tests/test_status_actions.py` | `tests/status_actions.rs` | RS-S7 |
| `tests/test_app_concurrency.py` | `tests/concurrency.rs` | RS-S7 |
| `tests/test_app.py` | `tests/app.rs` | RS-S5, RS-S9, RS-S10 |
| `tests/test_diff_viewer.py` | `tests/diff_viewer.rs` | RS-S8 |
| `tests/test_preview.py` | `src/document.rs` tests, `tests/preview.rs` | RS-S10 |
| `tests/test_file_jump.py` | `tests/file_jump.rs` | RS-S10 |
| `tests/test_icons.py` | `src/icons.rs` tests | RS-S10 |
| `tests/test_watcher.py` | `src/watcher.rs` tests | RS-S11 |
| `tests/test_auto_refresh.py` | `tests/auto_refresh.rs` | RS-S11 |

Every Python test name must map to a Rust test covering the same behavior, or
to a note in the story report explaining why it no longer applies (for example,
Textual-specific mechanics).

## 13. Story plan

Every coder prompt must include, verbatim:

- **"Do NOT boot the editor or run any browser/smoke test. Do not run the TUI
  binary interactively; tests only."**
- **"NEVER use `git stash`, `git checkout --`, or `git restore` on any file you
  did not intentionally edit for this task. If something unexpected changes,
  STOP and report it."**
- If a coder is stuck on an architectural decision, it escalates to
  `senior-coder` instead of guessing.

The standard verification, run inside the container, is:

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

### RS-S0 — Devcontainer, worktree, and SSH environment

**Outcome:** the user can start a Rust devcontainer for this worktree, SSH into
it, and use Git, cargo, and Claude Code inside.

**Verbatim story spec**

> Create `.devcontainer/devcontainer.json`, `.devcontainer/Dockerfile`,
> `.devcontainer/post-create.sh`, and `.devcontainer/up.sh` exactly as
> specified in section 3.2 of `docs/rust.md`, and add `.devcontainer/.ssh/` to
> `.gitignore`. Keep the files minimal and commented only where the reason is
> not obvious (the identical-path mount and the loopback SSH port). Do not add
> Rust sources, features beyond sshd, or VS Code customizations. This story runs
> on the host, which has no Rust toolchain; do not attempt to build or start the
> container.

**Target paths:** `.devcontainer/*`, `.gitignore`.

**Dependencies:** none.

**Verification** (coder, on the host):

```bash
bash -n .devcontainer/post-create.sh .devcontainer/up.sh
```

**Verification** (user):

1. `.devcontainer/up.sh` succeeds.
2. `ssh gitpane-dev` lands in the worktree.
3. Inside the container, `git status` and `git worktree list` work.
4. `cargo --version`, `cargo clippy --version`, `rustfmt --version`, and
   `claude --version` all work in the SSH shell.

### RS-S1 — Cargo scaffold and event loop

**Outcome:** an empty Rust GitPane starts, draws the tabs and status bar, and
quits cleanly.

**Verbatim story spec**

> Create the `gitpane` crate at the worktree root (edition 2024, commit
> `Cargo.lock`, add `target/` to `.gitignore`) with `src/main.rs`, `src/lib.rs`,
> `src/app.rs`, `src/runtime.rs`, `src/ui.rs`, and `src/theme.rs`.
>
> Implement:
> - The event channel, input thread, and main loop from section 5.2, with
>   drain-before-draw.
> - Terminal setup and teardown (raw mode, alternate screen, mouse capture),
>   restored on panic.
> - `App::update` returning effects.
> - Rendering of the `Changes` / `Files` tabs row (switching with `1`, `2`,
>   and clicks) and a `Branch:` status bar placeholder.
> - Quitting on `q` and Ctrl+C.
> - The theme tokens from section 10.10.
>
> Add workflow tests in `tests/app.rs` that render into `TestBackend` and prove
> tab switching by key and by click, and quitting.

**Target paths:** `Cargo.toml`, `Cargo.lock`, `.gitignore`, `src/*.rs` (listed),
`tests/app.rs`.

**Dependencies:** RS-S0 accepted by the user.

**Verification:** standard.

### RS-S2 — Git adapter

**Outcome:** a complete, tested Git adapter matching `gitpane/git.py`.

**Verbatim story spec**

> Implement `src/model.rs` and `src/git.rs` per sections 5.4 and 6: `Runner`,
> `SystemRunner`, `GitApi`, `CliGit`, porcelain v2 status parsing, commit and
> commit-file parsing, the diff commands with `-U1000000`, the
> stage/unstage/restore/clean operations, `repo_root`, `git_dirs`, and error
> text.
>
> Port every test in `tests/test_git.py` to `#[cfg(test)]` tests using a
> recording `Runner`, adjusting only the `-U` value. Do not run real Git in
> tests.

**Target paths:** `src/model.rs`, `src/git.rs`, `src/lib.rs`.

**Dependencies:** RS-S1.

**Verification:** standard.

### RS-S3 — Diff parser and tree-sitter highlighter

**Outcome:** diff and preview sources become documents whose visible rows can be
highlighted by byte range.

**Verbatim story spec**

> Implement:
> - `src/diff.rs` (section 7.1).
> - `src/highlight.rs`: the language registry, detection, per-side parsing,
>   viewport byte-range queries with the section 7.3 precedence, and the
>   section 7.5 palette.
> - `src/document.rs`: diff rows per section 7.6, and preview loading and
>   rows per section 7.7, including every message verbatim.
>
> Port the tests of `tests/test_diff.py`, `tests/test_diff_rendering.py`, and
> the pure `load_preview_view` tests of `tests/test_preview.py`. Add tests
> proving:
> - Removed rows are highlighted from the old side.
> - The gutter widens beyond 9,999 lines.
> - Unknown file types render plain.
> - Querying one visible line does not require highlighting others.
>
> Record any dropped language in the report.

**Target paths:** `src/diff.rs`, `src/highlight.rs`, `src/document.rs`,
`src/lib.rs`, `Cargo.toml`.

**Dependencies:** RS-S2.

**Verification:** standard.

### RS-S4 — CodeView

**Outcome:** a reusable virtual viewer with every behavior in section 8.

**Verbatim story spec**

> Implement `src/code_view.rs` per section 8: virtual rendering of document
> rows with tab expansion and cell-width cropping, unwrapped horizontal scroll,
> the wrapped visual-row index with continuation indent and resize anchoring,
> keys, wheel, the jump scrollbar with thumb dragging, selection with
> clipboard effects, and deferred scroll-to-row requests.
>
> Port every test of `tests/test_code_view.py` against `TestBackend`, and add
> the viewport-bounded render contract from section 12.

**Target paths:** `src/code_view.rs`, `src/lib.rs`.

**Dependencies:** RS-S3.

**Verification:** standard.

### RS-S5 — Application shell

**Outcome:** the full static layout of both tabs, with focus, hit-testing,
toasts, modals, and the shortcuts dialog, running on `FakeGit`.

**Verbatim story spec**

> Implement:
> - The section 10.1 layout for both tabs, with fixed initial sizes (resizing
>   comes in RS-S6).
> - The hit map and mouse routing from section 5.2, focus movement (Tab,
>   Shift+Tab, clicks, and `1`/`2` focus rules), and the status-bar button
>   hints.
> - Toasts from section 10.9, and the modal infrastructure (dimmed backdrop,
>   input capture).
> - The shortcuts dialog and first-launch marker from section 10.7.
> - Wiring `main.rs` to `CliGit`: resolve the repository root from the launch
>   directory. Outside a repository, print Git's error to stderr and exit with
>   status 1, before touching the terminal.
>
> Create the `tests/common/mod.rs` harness (section 12). Port the startup,
> shortcut, and first-launch tests from `tests/test_app.py`, and the layout and
> readability tests from `tests/test_theme.py` that apply to this story.
>
> Lists, trees, and viewers may show placeholder content until their stories.

**Target paths:** `src/app.rs`, `src/ui.rs`, `src/runtime.rs`, `src/theme.rs`,
`tests/common/mod.rs`, `tests/app.rs`, `tests/theme.rs`.

**Dependencies:** RS-S4.

**Verification:** standard.

### RS-S6 — Resizable layout

**Outcome:** the sidebar, its three sections, and the Files tree resize by
dragging, exactly as in section 9.

**Verbatim story spec**

> Implement `src/layout.rs` and the splitter behavior from section 9:
> - `resize_pair`, and weight freezing on drag start.
> - Adjacent-only resizing.
> - Proportional scaling on terminal resize after a drag.
> - Minimums, and graceful handling of tiny terminals.
> - Hover and drag appearance, and mouse capture for the whole drag.
> - The new Files tab splitter.
>
> Port `tests/test_splitter.py` and `test_resizing_keeps_usable_panes_and_scrolling`.
> Add tests for every outcome listed in section 9.4.

**Target paths:** `src/layout.rs`, `src/ui.rs`, `src/app.rs`, `tests/resize.rs`,
`tests/theme.rs`.

**Dependencies:** RS-S5.

**Verification:** standard.

### RS-S7 — Changes lists and actions

**Outcome:** status lists load, and files can be checked, staged, unstaged, and
discarded, one at a time or in bulk, with serialized Git work.

**Verbatim story spec**

> Implement:
> - The git queue from section 5.3, and manual status refresh and mutations
>   from section 11.1.
> - The status lists from section 10.2 (labels, keys, checkbox columns, row
>   actions, bulk actions, unsupported rows, and row states).
> - The discard confirmation dialog from section 10.7.
> - The `s`, `d`, and Space keys, and the error toasts.
>
> Port `tests/test_status_actions.py` and `tests/test_app_concurrency.py`.
> Include:
> - Controlled completion order proving newest-result-wins.
> - Mutation serialization in request order.
> - That no status read interleaves with a mutation job.

**Target paths:** `src/app.rs`, `src/ui.rs`, `src/runtime.rs`,
`tests/status_actions.rs`, `tests/concurrency.rs`, `tests/common/mod.rs`.

**Dependencies:** RS-S6.

**Verification:** standard.

### RS-S8 — Diff pane

**Outcome:** selecting a working-tree entry shows its highlighted diff, with
change navigation.

**Verbatim story spec**

> Implement section 10.5:
> - Request, apply, and invalidate.
> - The first-change scroll, and `n`/`p` with the title-bar buttons.
> - `w`, the loading states, and error handling.
>
> Port `tests/test_diff_viewer.py`, except the quiet-reload tests (RS-S11), and
> the diff rendering assertions of `tests/test_theme.py`.

**Target paths:** `src/app.rs`, `src/ui.rs`, `tests/diff_viewer.rs`,
`tests/theme.rs`.

**Dependencies:** RS-S7.

**Verification:** standard.

### RS-S9 — History

**Outcome:** the Commits section lists recent commits, expands them lazily, and
shows historical diffs.

**Verbatim story spec**

> Implement:
> - The commit tree from section 10.3, including gitmoji expansion with the
>   dim short hash.
> - Manual history refresh and the empty-lists commit selection from section
>   11.4.
> - Lazy commit files and the `(no changed files)` leaf.
> - Historical diffs through the shared diff pane.
>
> Port the commit tests from `tests/test_app.py`, including
> `format_commit_label`.

**Target paths:** `src/app.rs`, `src/ui.rs`, `tests/app.rs`.

**Dependencies:** RS-S8.

**Verification:** standard.

### RS-S10 — Files tab, preview, and file jump

**Outcome:** the Files tab browses the launch directory, previews files, and
jumps to files by name.

**Verbatim story spec**

> Implement:
> - The Files tree, icons, and preview pane from section 10.6, with previews
>   through CodeView (independent wrap).
> - Refresh behavior.
> - The file jump dialog from section 10.7.
>
> Port `src/icons.rs` verbatim from `gitpane/icons.py`, `tests/test_icons.py`,
> the remaining `tests/test_preview.py` workflows, `tests/test_file_jump.py`,
> and the file-tree tests from `tests/test_app.py`.

**Target paths:** `src/icons.rs`, `src/app.rs`, `src/ui.rs`, `tests/preview.rs`,
`tests/file_jump.rs`, `tests/app.rs`.

**Dependencies:** RS-S9.

**Verification:** standard.

### RS-S11 — Watcher and automatic refresh

**Outcome:** the UI follows repository changes quietly, preserving state, and
reports failures once per streak.

**Verbatim story spec**

> Implement:
> - `src/watcher.rs` (classification, the debounced watcher thread, and
>   lifecycle messages) per section 11.6.
> - Automatic refresh, quiet apply, open-diff reconciliation, quiet diff
>   reload, and quiet history refresh per sections 11.2–11.4.
>
> Port `tests/test_watcher.py`, `tests/test_auto_refresh.py`, and the
> quiet-reload tests of `tests/test_diff_viewer.py`. Watcher classification
> tests use paths only; workflow tests feed invalidations through the harness,
> not a real filesystem.

**Target paths:** `src/watcher.rs`, `src/app.rs`, `src/runtime.rs`,
`tests/auto_refresh.rs`, `tests/diff_viewer.rs`.

**Dependencies:** RS-S10.

**Verification:** standard.

### RS-S12 — Cutover

**Outcome:** the Rust application replaces the Python one on `main`.

**Verbatim story spec**

> Audit parity: map every `README.md` control and every Python test name to a
> Rust test or a documented reason, and fix gaps in scoped follow-up stories
> before continuing.
>
> Then remove `gitpane/`, the Python tests, `pyproject.toml`, and `uv.lock`, and
> rewrite `README.md` (requirements, `cargo install --path .`, controls) and
> the testing rules in `AGENTS.md` for Rust.
>
> Make the devcontainer work from the main checkout: `workspaceFolder` becomes
> `${localWorkspaceFolder}`, and `up.sh` uses the repository root.
>
> Update the status table and completion notes in this document. The merge to
> `main` is done by the orchestrator after user approval.

**Target paths:** repository-wide deletions, `README.md`, `AGENTS.md`,
`.devcontainer/*`, `docs/rust.md`.

**Dependencies:** RS-S11, and the user's smoke test of the complete app.

**Verification:** standard, plus this search returns nothing:

```bash
grep -rnE "uv run|pytest|textual" --exclude-dir=docs --exclude-dir=target --exclude-dir=.git .
```

## 14. Estimate

About 4,500–5,500 lines of Rust and 4,000–5,000 lines of tests. That is roughly
three to five focused weeks for one developer, or less with the agent workflow.
The riskiest stories are RS-S5 (focus and mouse routing), RS-S6 (resizing), and
RS-S11 (refresh reconciliation). Diff rendering itself, the reason for the
rewrite, is among the simpler parts.

## Status

| Story | Status | Depends on | Primary deliverable |
| --- | --- | --- | --- |
| RS-S0 — Devcontainer environment | Not started | — | Worktree-safe devcontainer with SSH and Claude Code |
| RS-S1 — Cargo scaffold | Not started | RS-S0 | Event loop, tabs, status bar, quality gates |
| RS-S2 — Git adapter | Not started | RS-S1 | `GitApi`, `CliGit`, parsers, adapter tests |
| RS-S3 — Diff and highlighting | Not started | RS-S2 | Parser, tree-sitter viewport highlighting, documents |
| RS-S4 — CodeView | Not started | RS-S3 | Virtual viewer with wrap, scrollbars, selection |
| RS-S5 — Application shell | Not started | RS-S4 | Layout, focus, hit map, toasts, modals, shortcuts |
| RS-S6 — Resizable layout | Not started | RS-S5 | Splitters on both tabs |
| RS-S7 — Changes lists and actions | Not started | RS-S6 | Status lists, actions, git queue |
| RS-S8 — Diff pane | Not started | RS-S7 | Highlighted diffs and change navigation |
| RS-S9 — History | Not started | RS-S8 | Commit tree and historical diffs |
| RS-S10 — Files tab | Not started | RS-S9 | Files tree, preview, file jump |
| RS-S11 — Automatic refresh | Not started | RS-S10 | Watcher and quiet reconciliation |
| RS-S12 — Cutover | Not started | RS-S11 | Python removed, docs updated, merged |
