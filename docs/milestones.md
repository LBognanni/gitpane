# Milestone 1: Repository status model and parsing

## Goal

Create the initial Python package, represent staged and unstaged file changes, and parse Git porcelain v2 status output. The milestone is complete when `uv run python -m gitpane.git` prints the parsed status of the real repository from which it is run.

Repository baseline: the repository currently contains documentation only. It has no Python package, project metadata, lockfile, or test suite, so the minimum Python/`uv` scaffolding is part of this milestone.

## Scope boundary

### In scope

- A minimal `uv`-managed Python project and importable `gitpane` package.
- The `Side`, `FileEntry`, and `RepoState` types specified in `docs/design-spec.md`.
- A single Git subprocess helper used by repository-root and status operations.
- Repository-root discovery with `git rev-parse --show-toplevel`.
- NUL-delimited `git status --porcelain=v2 -z --untracked-files=all` parsing for ordinary (`1`) and untracked (`?`) records.
- Separate staged and unstaged entries when both porcelain X and Y columns report a change.
- A module entry point that prints parsed status for a real repository.
- Focused unit tests for parser behavior; Git itself is not unit-tested.

### Out of scope

- `git diff`, including special handling for untracked files.
- Stage and unstage commands.
- Rename/copy (`2`) and unmerged (`u`) records, merge-conflict support, submodule-specific behavior, and binary-file behavior.
- Diff parsing/rendering, Textual UI work, syntax highlighting, file watching, caching, or threading.
- Changes to `README.md`, `docs/design-spec.md`, or `docs/workflow.md`.

## Locked decisions

| Area | Decision |
| --- | --- |
| Package layout | Use a simple repository-root package at `gitpane/`; do not introduce a `src/` layout for this small application. |
| Project tooling | Add `pyproject.toml` with `requires-python = ">=3.11"` and a generated `uv.lock`. Runtime code remains standard-library-only; keep Ruff, mypy, and pytest in the development dependency group. Use `uv` for every Python/tool invocation. Do not add a build backend until the project needs distribution packaging. |
| Model contract | `Side` is an `Enum` with `STAGED` and `UNSTAGED`; `FileEntry` is frozen and contains `path: str`, `side: Side`, and `status: str`; `RepoState` contains `root: Path` plus mutable staged and unstaged lists. Preserve repository-relative paths exactly as Git emits them. |
| Git execution | Implement one private `_run` helper around `subprocess.run`. It receives a working directory, prepends `git`, captures text stdout, checks failures, and sets `GIT_OPTIONAL_LOCKS=0` while preserving the existing environment. Do not add a shell, custom exception hierarchy, or command abstraction. |
| Root discovery | `repo_root()` runs `rev-parse --show-toplevel` from the supplied path or current directory and returns a `Path` from stripped stdout. Git command failures propagate rather than being translated. |
| Status command | `status(root)` runs `status --porcelain=v2 -z --untracked-files=all` at `root` and returns a `RepoState` rooted there. |
| Parsing seam | Keep porcelain parsing in one small private pure function so it can be tested from literal status output without mocking or invoking Git. Split ordinary records with a bounded split so spaces in paths survive. Empty records are ignored. |
| Supported records | Parse only `1` and `?`. Silently skip `2`, `u`, and unknown record kinds as required by this milestone's scope. |
| X/Y mapping | For an ordinary record, create a staged entry from non-dot X and an unstaged entry from non-dot Y. Preserve `A`, `M`, and `D`; normalize porcelain type-change `T` to model status `M`. Ignore any other unsupported code. This naturally emits two entries for a file changed in both index and worktree. |
| Untracked mapping | A `?` record creates one unstaged entry with status `?`; it never creates a staged entry. |
| Ordering | Preserve Git's record order independently in each output list; do not sort or deduplicate. |
| CLI output | `gitpane.git.main()` discovers the repository, parses status, and prints deterministic `Staged:` and `Unstaged:` sections containing one `STATUS PATH` line per entry. Empty sections still print their heading. No argument parser or formatting dependency is needed. |
| Testing | Test application parsing with literal porcelain records. Do not create temporary repositories or test whether Git commands themselves work. The required real-repository module invocation is milestone verification, not a unit test. |

## Story status

| Story | Title | Status |
| --- | --- | --- |
| 1 | Bootstrap the Python package and toolchain | Complete |
| 2 | Add the repository status model | Complete |
| 3 | Parse and print repository status | Complete |
| 4 | Final cleanup and milestone verification | Pending |

## Story 1: Bootstrap the Python package and toolchain

### Files

- Create `pyproject.toml`.
- Create `uv.lock` using `uv lock`/`uv sync`; do not hand-edit it.
- Create `gitpane/__init__.py`.

### Work

1. Define the `gitpane` project with `requires-python = ">=3.11"` in `pyproject.toml` without runtime dependencies or a build backend.
2. Add a development dependency group containing only `mypy`, `pytest`, and `ruff`.
3. Configure concise Ruff and mypy defaults appropriate for the new package and tests. Avoid packaging or tooling configuration not needed by this milestone.
4. Add an intentionally minimal package initializer; do not re-export future model or Git APIs.
5. Generate the lockfile with `uv`.

### Acceptance criteria

- A fresh `uv sync --dev` succeeds from the repository root.
- `gitpane` imports without side effects.
- The metadata introduces no application or UI dependencies.
- The lockfile matches `pyproject.toml` and is generated by `uv`.

### Verification

```bash
uv sync --dev
uv run python -c "import gitpane"
uv run ruff check gitpane/__init__.py
uv run ruff format --check gitpane/__init__.py
uv run mypy gitpane
```

## Story 2: Add the repository status model

### Files

- Create `gitpane/model.py`.

### Work

1. Implement `Side`, `FileEntry`, and `RepoState` exactly as defined by the model contract above.
2. Use `pathlib.Path`, `enum.Enum`, and `dataclasses`; do not add model methods, validation, serialization, or derived state.
3. Keep staged and unstaged list ownership explicit at construction time; do not use shared mutable defaults.

### Acceptance criteria

- `Side.STAGED` and `Side.UNSTAGED` are distinct enum members.
- `FileEntry` has only the specified three fields and cannot be mutated after construction.
- `RepoState` stores its root and independent staged/unstaged `FileEntry` lists.
- The implementation remains a direct, typed representation of the design specification with no Git knowledge.

### Verification

```bash
uv run python -c "from pathlib import Path; from gitpane.model import FileEntry, RepoState, Side; entry = FileEntry('file.txt', Side.STAGED, 'M'); state = RepoState(Path('.'), [entry], []); assert state.staged == [entry] and not state.unstaged"
uv run ruff check gitpane/model.py
uv run ruff format --check gitpane/model.py
uv run mypy gitpane/model.py
```


## Story 3: Parse and print repository status

### Files

- Create `gitpane/git.py`.
- Create `tests/test_git.py`.

### Work

1. Add the single `_run` helper, `repo_root()`, and `status()` according to the locked command and environment decisions.
2. Add the private pure parser used by `status()`. Parse NUL-separated output, use the porcelain v2 ordinary-record field layout, and preserve the complete final path field.
3. Implement the X/Y, untracked, unsupported-record, ordering, and type-change rules above.
4. Add `main()` plus a `if __name__ == "__main__"` guard that prints the two status sections. Keep import side effects at zero.
5. Unit-test the parser with compact literal records covering:
   - staged-only, unstaged-only, and staged-plus-unstaged ordinary changes;
   - added and deleted status codes;
   - `T` normalization to `M`;
   - an untracked path, including a path containing spaces;
   - ignored empty records and skipped `2`, `u`, and unknown records;
   - retained record order and the supplied repository root.
6. Do not invoke Git, create a temporary repository, or assert Git's own behavior in unit tests.

### Acceptance criteria

- Running status in a repository returns a `RepoState` whose root is the discovered/supplied root.
- Every supported ordinary X/Y change appears on the correct side with the expected model status, including two entries for a dual-sided path.
- Every untracked record appears only in `unstaged` with status `?`.
- Paths containing spaces are not truncated, and list ordering follows porcelain output.
- Unsupported record kinds do not crash or leak partial entries into the result.
- `_run` is the only subprocess execution path and applies both the repository working directory and `GIT_OPTIONAL_LOCKS=0`.
- `uv run python -m gitpane.git` succeeds in this repository and prints `Staged:` and `Unstaged:` sections reflecting its current real status.

### Verification

```bash
uv run pytest tests/test_git.py
uv run ruff check gitpane/git.py tests/test_git.py
uv run ruff format --check gitpane/git.py tests/test_git.py
uv run mypy gitpane tests
uv run python -m gitpane.git
```


## Story 4: Final cleanup and milestone verification

### Files

- Review and, only when a fix is required, edit `pyproject.toml`.
- Regenerate, but never hand-edit, `uv.lock` if metadata changed.
- Review and, only when a fix is required, edit `gitpane/__init__.py`.
- Review and, only when a fix is required, edit `gitpane/model.py`.
- Review and, only when a fix is required, edit `gitpane/git.py`.
- Review and, only when a fix is required, edit `tests/test_git.py`.

### Work

1. Review the complete milestone diff for accidental complexity, duplicated parsing paths, stale imports, debug output, and work outside the scope boundary.
2. Apply only fixes needed to meet this milestone; do not begin diff, stage/unstage, or UI work.
3. Run the complete milestone checks once and verify the required command against the current real repository.
4. Confirm that any generated lockfile is current and that no cache, virtual-environment, coverage, or build artifacts are included in the intended changes.
5. Leave status-table updates and commits to the orchestrator as required by `docs/workflow.md`.

### Acceptance criteria

- All stories' acceptance criteria remain satisfied together.
- The implementation is the smallest clear solution for model and status parsing, with no later-milestone APIs added speculatively.
- The test suite exercises parser logic without testing Git itself.
- The real-repository command prints parsed status successfully.
- Only milestone-owned files are changed by implementation work; generated/local artifacts are absent from the intended diff.
- No editor/UI/browser/smoke process is booted.

### Verification

```bash
uv sync --dev
uv run ruff check gitpane tests
uv run ruff format --check gitpane tests
uv run mypy gitpane tests
uv run pytest
uv run python -m gitpane.git
git status --short
```
