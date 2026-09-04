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
| 4 | Final cleanup and milestone verification | Complete |

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


# Milestone 3: Git diff and index operations

## Goal

Complete the remaining Step 2 Git operations from `docs/design-spec.md`: produce
a full-context unified diff for a selected staged, unstaged, or untracked
`FileEntry`, and provide whole-file stage and unstage operations. The milestone
is complete when the command-building and return-code policy are covered by
unit tests without invoking Git, and all existing status and unified-diff tests
continue to pass.

Repository baseline: Milestones 1 and 2 are complete. `gitpane/git.py` already
has the single `_run()` subprocess path, repository-root discovery, status
parsing, and the status-printing module entry point. `FileEntry.side` and
`FileEntry.status` contain all information needed to choose a diff command.
The currently untracked `gitpane/__pycache__/` and `tests/__pycache__/`
directories are known artifacts from approved verification. They are not
milestone work: do not edit, delete, stage, or otherwise clean them up, and do
not treat their presence in `git status --short` as a failure.

## Scope boundary

### In scope

- Extending the existing `_run()` helper just enough to accept an explicit set
  of successful return codes while retaining its current default failure
  behavior.
- Full-context, no-color, no-external-diff output for staged and tracked
  unstaged entries.
- Unified no-index diff output for untracked entries by comparing `/dev/null`
  with the repository-relative path.
- Treating return code `1` as successful only for the untracked no-index diff;
  its standard output is still returned.
- Whole-path stage and unstage commands, with `--` before every user-controlled
  path.
- Focused tests of GitPane's exact argument construction, output forwarding,
  and subprocess error policy using monkeypatches/fakes. The tests do not run
  Git or assert Git's behavior.

### Out of scope

- Changes to status parsing, status display, the `FileEntry`/`RepoState` model,
  or unified-diff parsing in `gitpane/diff.py`.
- Hunk or line staging, partial index updates, pathspec expansion, multiple-path
  operations, rename/conflict/binary handling, or special submodule behavior.
- Interpreting, parsing, caching, highlighting, or rendering the returned diff.
- Adding a CLI for diff/stage/unstage or changing the existing
  `python -m gitpane.git` output.
- UI/Textual work, application wiring, file watching, threading, or later
  design-spec steps.
- Adding dependencies or changing `pyproject.toml`, `uv.lock`,
  `gitpane/__init__.py`, `gitpane/model.py`, `gitpane/diff.py`, README, or any
  design/workflow document.
- Creating repositories or files to exercise Git, invoking Git from tests, or
  testing whether the selected Git commands work.
- Booting the application or performing editor, browser, or smoke checks.
- Removing, ignoring, staging, or modifying the known untracked
  `gitpane/__pycache__/` and `tests/__pycache__/` artifacts.

## Locked decisions

| Area | Decision |
| --- | --- |
| Public function signatures | Add `diff(root: Path, entry: FileEntry) -> str`, `stage(root: Path, path: str) -> None`, and `unstage(root: Path, path: str) -> None` to `gitpane/git.py`. The design specification's `diff(entry)`/`stage(path)`/`unstage(path)` notation names the operations but omits repository context; use an explicit first `root` argument, consistent with the existing `status(root)` API and without global repository state. Do not re-export these functions from `gitpane/__init__.py`. |
| Shared execution path | Keep `_run()` as the only call to `subprocess.run`; no operation may execute a subprocess directly. Preserve the existing `git` prefix, `cwd`, captured text output, inherited environment, and `GIT_OPTIONAL_LOCKS=0`. Do not introduce a runner class or custom exception. |
| Return-code policy | Add a keyword-only `allowed_returncodes: tuple[int, ...] = (0,)` parameter after `_run()`'s variadic Git arguments. Run the subprocess without automatic checking, return stdout when its code is allowed, and otherwise raise the standard `subprocess.CalledProcessError` via the completed process's normal check mechanism. Existing callers therefore continue to accept only `0`. Pass `(0, 1)` only for the untracked no-index diff; code `1` from every other command and code `2` or higher from every command still propagate. |
| Staged diff command | For `entry.side is Side.STAGED`, run exactly `git diff --cached -U9999 --no-color --no-ext-diff -- <entry.path>` at `root` and return stdout unchanged. The entry status does not alter this branch. |
| Tracked unstaged diff command | For `entry.side is Side.UNSTAGED` and `entry.status != "?"`, run exactly `git diff -U9999 --no-color --no-ext-diff -- <entry.path>` at `root` and return stdout unchanged. |
| Untracked diff command | For `entry.side is Side.UNSTAGED` and `entry.status == "?"`, run exactly `git diff --no-index -U9999 --no-color --no-ext-diff -- /dev/null <entry.path>` at `root`, allowing return codes `0` and `1`. Use the literal `/dev/null` required by the design; do not read the file in Python or synthesize patch text. A staged entry is governed by its side even if malformed test/application data gives it status `?`. |
| Path safety | Preserve every path string exactly and place it after `--`. Do not normalize it, resolve it, convert it to an absolute path, split it, quote it manually, or use a shell. Git receives each path as one subprocess argument. |
| Stage command | `stage(root, path)` runs exactly `git add -- <path>` through `_run()` and ignores successful stdout. It returns `None`; failures propagate. |
| Unstage command | `unstage(root, path)` runs exactly `git restore --staged -- <path>` through `_run()` and ignores successful stdout. It returns `None`; failures propagate. Supporting repositories without a resolvable `HEAD` is not part of this milestone. |
| Testing boundary | Extend `tests/test_git.py`. Monkeypatch `_run()` when testing operation-to-command mapping and monkeypatch `subprocess.run` when testing `_run()` itself. Assert calls and application handling of fake completed processes; never invoke Git, create a temporary repository, or test Git output semantics. No additional mocking dependency is needed. |

## Story execution rules

Each story must be dispatched with its specification, the milestone scope and
locked decisions, and the required coder-prompt rules from
`docs/workflow.md`: do not boot the editor/application or run browser/smoke
tests; never use `git stash`, `git checkout --`, or `git restore` on files not
intentionally edited; stop and report unexpected changes; and escalate an
unresolved architectural decision to the senior coder rather than guessing.
The existing cache directories must remain untouched. Use
`PYTHONDONTWRITEBYTECODE=1` for Python verification so the approved cache
artifacts are not rewritten.

## Story status

| Story | Title | Status |
| --- | --- | --- |
| 1 | Build staged, unstaged, and untracked diff commands | Complete |
| 2 | Add whole-file stage and unstage commands | Complete |
| 3 | Final cleanup and milestone verification | Complete |

## Story 1: Build staged, unstaged, and untracked diff commands

### Files

- Edit `gitpane/git.py`.
- Edit `tests/test_git.py`.

### Work

1. Extend `_run()` with the locked keyword-only allowed-return-code parameter.
   Preserve every existing subprocess setting and keep `0` as the default and
   only successful code for existing callers.
2. Use the completed process's return code to return stdout for an allowed code
   and raise the standard subprocess error for every other code. Do not catch,
   wrap, log, or convert the error.
3. Add `diff(root, entry)` and select exactly one of the three locked commands:
   staged by side, untracked by unstaged side plus `?` status, and otherwise
   tracked unstaged. Return `_run()` output without stripping or parsing it.
4. Add focused `_run()` tests with a fake `subprocess.run` that prove:
   - the command is a list beginning with `git`, the supplied root is `cwd`,
     text stdout is captured, and shell execution is not introduced;
   - the inherited environment is retained and `GIT_OPTIONAL_LOCKS` is
     overridden to `0`;
   - stdout is returned for code `0`, a nonzero code raises by default, code
     `1` can be explicitly accepted, and code `2` still raises when only
     `(0, 1)` is accepted.
5. Add `diff()` tests by replacing `_run()` with a recording fake. Cover the
   exact ordered argument tuple for staged, tracked unstaged, and untracked
   entries, including a path containing spaces and leading dashes as one
   unchanged argument. Prove only the untracked call supplies
   `allowed_returncodes=(0, 1)` and that returned diff text is forwarded
   unchanged.
6. Keep all tests process-local. Do not invoke Git or make assertions about how
   Git itself interprets the commands.

### Acceptance criteria

- `_run()` remains the sole subprocess boundary and preserves its existing
  command, working-directory, text-capture, and environment behavior.
- Existing root and status calls still raise on any nonzero return code without
  needing call-site changes.
- `diff()` emits the exact command for each supported `FileEntry` category,
  protects the path with `--`, and returns stdout byte-for-text unchanged.
- An untracked no-index diff accepts code `1`; no other new success exception is
  introduced, and genuine errors continue to propagate as
  `subprocess.CalledProcessError`.
- Tests verify GitPane's construction and policy entirely through fakes and do
  not run or test Git.
- Existing status tests remain green and no out-of-scope files or cache
  artifacts are modified.

### Verification

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_git.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff check gitpane/git.py tests/test_git.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff format --check gitpane/git.py tests/test_git.py
PYTHONDONTWRITEBYTECODE=1 uv run mypy gitpane/git.py tests/test_git.py
git status --short
```

The status command may continue to show the two known untracked cache
directories. They must not be removed, modified, or staged.

## Story 2: Add whole-file stage and unstage commands

### Files

- Edit `gitpane/git.py`.
- Edit `tests/test_git.py`.

### Work

1. Add `stage(root, path)` as the smallest wrapper around the exact locked
   `add` command. Ignore `_run()`'s successful stdout and return `None`.
2. Add `unstage(root, path)` as the smallest wrapper around the exact locked
   `restore --staged` command. Ignore successful stdout and return `None`.
3. Add tests using a recording `_run()` fake that assert the supplied root and
   exact ordered arguments for each function. Use a path containing spaces and
   beginning with a dash to prove it remains one argument after `--`.
4. Have the fake return nonempty text and assert both APIs still return `None`.
   Have it raise a sentinel `subprocess.CalledProcessError` and assert each API
   lets that same failure propagate; do not add operation-specific error
   handling.
5. Do not execute stage/unstage against this or any temporary repository, and
   do not add multi-path convenience behavior or application/UI wiring.

### Acceptance criteria

- `stage()` constructs only `git add -- <path>` at the supplied root.
- `unstage()` constructs only `git restore --staged -- <path>` at the supplied
  root.
- Paths are forwarded unchanged as a single argument after `--`.
- Both operations return `None` on success and preserve the standard subprocess
  exception on failure.
- Unit tests establish application command construction and error propagation
  without invoking or testing Git.
- Story 1's diff behavior and all prior status behavior remain unchanged.

### Verification

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_git.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff check gitpane/git.py tests/test_git.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff format --check gitpane/git.py tests/test_git.py
PYTHONDONTWRITEBYTECODE=1 uv run mypy gitpane/git.py tests/test_git.py
git status --short
```

The status command may continue to show the two known untracked cache
directories. They must not be removed, modified, or staged.

## Story 3: Final cleanup and milestone verification

### Files

- Review and, only when a milestone fix is required, edit `gitpane/git.py`.
- Review and, only when a milestone fix is required, edit `tests/test_git.py`.
- Do not modify any other file during cleanup; status-table documentation
  updates and commits remain the orchestrator's responsibility.

### Work

1. Review the complete Milestone 3 implementation diff for duplicated command
   execution, unnecessary abstractions, stale imports, broad exception
   handling, path mutation, debug output, and work outside the scope boundary.
2. Confirm that `_run()` is still the only subprocess call, only the no-index
   untracked diff accepts code `1`, every user path follows `--`, and all three
   diff branches plus stage/unstage have exact command-construction tests.
3. Confirm tests use only fakes/monkeypatching and literal model values: no Git
   invocation, temporary repository, filesystem setup, or claims about Git's
   own behavior are present.
4. Apply only fixes required by this milestone. Do not begin UI integration,
   diff rendering, highlighting, or watcher work, and do not change project
   metadata or prior milestone modules.
5. Run the complete project verification once with bytecode writing disabled.
   Do not run a real diff, stage, unstage, or app command as a smoke test.
6. Inspect `git status --short`. Treat the existing untracked
   `gitpane/__pycache__/` and `tests/__pycache__/` as known approved artifacts:
   do not remove, edit, ignore, or stage them. Report any other unexpected file
   and stop rather than using a destructive cleanup command.
7. Leave status-table updates and all commits to the orchestrator, as required
   by `docs/workflow.md`.

### Acceptance criteria

- All Milestone 3 story acceptance criteria hold together with all prior tests.
- The implementation is the smallest clear extension of the existing
  functional Git API and has no second subprocess path or global repository
  state.
- Ruff formatting/lint, strict mypy, and the complete pytest suite pass.
- Tests cover exact commands, output/return behavior, and allowed/disallowed
  return codes without executing Git or testing Git itself.
- Only `gitpane/git.py` and `tests/test_git.py` are changed by implementation
  work; the known untracked cache directories remain untouched and unstaged.
- No application, editor, UI, browser, smoke process, or real mutating Git
  operation is run.

### Verification

```bash
PYTHONDONTWRITEBYTECODE=1 uv run ruff check gitpane tests
PYTHONDONTWRITEBYTECODE=1 uv run ruff format --check gitpane tests
PYTHONDONTWRITEBYTECODE=1 uv run mypy gitpane tests
PYTHONDONTWRITEBYTECODE=1 uv run pytest
git diff --check -- gitpane/git.py tests/test_git.py
git status --short
```

Expected status may include the intentionally untouched untracked
`gitpane/__pycache__/` and `tests/__pycache__/` directories in addition to the
milestone's intended tracked edits. Do not attempt to clean those artifacts.


# Milestone 2: Unified diff parsing

## Goal

Implement Step 3 of `docs/design-spec.md`: parse unified-diff text with
`unidiff.PatchSet` into an ordered flat list of typed `Row` values, locate the
first changed row, and provide a small module entry point that reads a unified
diff from standard input and prints the total row count and first-change index.
The milestone is complete when a representative diff can be piped to
`uv run python -m gitpane.diff` and the expected summary is printed.

Repository baseline: Milestone 1 is complete. The package, strict mypy/Ruff/
pytest tooling, status model, and status parser already exist. There is no diff
module or runtime dependency yet. The existing `docs/workflow.md` change is
unrelated to this milestone and must be left untouched.

## Scope boundary

### In scope

- The `unidiff` runtime dependency and regenerated `uv.lock`.
- Parsing ordinary textual unified diffs through `unidiff.PatchSet`.
- One immutable, tuple-compatible `Row` record with `old_no`, `new_no`, `text`,
  and `kind` fields.
- Flattening all parsed files and hunks into rows in patch order.
- Context, addition, and removal rows, including their applicable old/new line
  numbers.
- A zero-based first-change lookup.
- A minimal standard-input module entry point for the stated printing
  milestone.
- Focused tests of GitPane's row mapping, ordering, first-change lookup, and
  summary output using literal unified-diff text.

### Out of scope

- Changes to `gitpane/git.py`, including adding the Step 2 `diff()`, `stage()`,
  or `unstage()` Git commands and untracked-file handling.
- Invoking Git or testing Git's behavior.
- Side-by-side diff alignment, hunk or line staging, rename, conflict, binary,
  malformed-patch, or combined-diff support.
- File headers, hunk headers, and `\\ No newline at end of file` markers as
  rendered rows.
- Syntax highlighting, full-file reconstruction, UI/Textual work, scrolling,
  file watching, caching, or threading.
- Command-line arguments, reading a named file, output styling, or a reusable
  reporting/formatting abstraction.
- Changes to `gitpane/model.py`, `gitpane/__init__.py`, `README.md`,
  `docs/design-spec.md`, or `docs/workflow.md`.
- Booting the application or performing browser/smoke testing.

## Locked decisions

| Area | Decision |
| --- | --- |
| Public module API | Create `gitpane/diff.py` with `parse(text: str) -> list[Row]`, `first_change_index(rows: Sequence[Row]) -> int | None`, and `main() -> None`. Do not re-export these names from `gitpane/__init__.py`. |
| Row representation | Implement `Row` as a typed `typing.NamedTuple`, the typed equivalent of the design's `namedtuple`, with fields in exactly this order: `old_no: int | None`, `new_no: int | None`, `text: str`, and `kind: Literal["context", "add", "remove"]`. Do not add methods or metadata fields. |
| Parser | Construct `unidiff.PatchSet` directly from the supplied string. Iterate files, hunks, and lines in library order and return one flat list; do not retain file/hunk objects or create an intermediate domain model. Let `unidiff` parsing errors propagate without translation. |
| Line mapping | Map context to both source and target line numbers, removal to source only, and addition to target only, using the line numbers supplied by `unidiff`. Map kinds to exactly `context`, `remove`, and `add`. |
| Row text | Use the patch line's content without its diff marker. Remove at most one terminal line ending (`\n`, and a preceding `\r` when present); preserve all other whitespace and do not synthesize a newline for a final unterminated line. |
| Patch metadata | Emit rows only for context/add/remove lines inside hunks. Patch/file headers, hunk headers, and no-newline markers are not rows. Empty patches produce an empty list. |
| First change | Return the zero-based index of the first row whose kind is `add` or `remove`. Return `None` for an empty list or an all-context list. Do not prefer additions over removals or offset the index for future UI chrome. |
| Printing milestone | `main()` reads all unified-diff text from `sys.stdin`, parses it, and prints exactly two lines: `Rows: N` and `First change: I`, where `I` is the integer index or `None`. Keep the `if __name__ == "__main__"` guard; add no argument parser or Git integration. |
| Dependency | Add `unidiff>=1.0.0` as the sole `[project]` runtime dependency and regenerate `uv.lock` through `uv add`/`uv lock`; never hand-edit the lockfile. Add no development dependency or import suppression: unidiff 1.x publishes inline typing metadata, so its `PatchSet` import must pass strict mypy without an ignore. |
| Testing | Add `tests/test_diff.py` with literal patch strings. Test GitPane's transformation and output, not `unidiff` internals and not Git. No fixture file, subprocess test, temporary repository, snapshot library, or mocking framework is needed. |

## Story status

| Story | Title | Status |
| --- | --- | --- |
| 1 | Add the dependency and flatten unified diffs into rows | Complete |
| 2 | Locate the first change and print the diff summary | Complete |
| 3 | Final cleanup and milestone verification | Complete |

## Story 1: Add the dependency and flatten unified diffs into rows

### Files

- Edit `pyproject.toml`.
- Regenerate `uv.lock`; do not hand-edit it.
- Create `gitpane/diff.py`.
- Create `tests/test_diff.py`.

### Work

1. Add `unidiff>=1.0.0` as a runtime dependency with `uv`, retaining the
   existing development dependency group and tool configuration unchanged.
2. Define the typed `Row` record and `parse()` API according to the locked
   contracts above. Import `unidiff.PatchSet` without a type-ignore comment.
3. Flatten every file and hunk in patch order. Map context, removal, and
   addition lines to the exact kinds and nullable source/target numbers above.
4. Strip only the line terminator from each value. Do not strip indentation or
   trailing spaces, and do not include diff markers or patch metadata.
5. Add focused tests using literal unified diffs that cover:
   - context, removal, and addition field mapping and zero/one-sided numbers;
   - text with leading and trailing spaces;
   - multiple hunks and multiple files remaining in source order;
   - an empty patch returning an empty list;
   - a final changed line without a newline not losing content.
6. Do not add first-change or command-line behavior in this story; those belong
   to Story 2.

### Acceptance criteria

- `parse()` uses `PatchSet` and returns only flat `Row` values in patch order.
- Every row has the exact field order, value types, kind spelling, line-number
  mapping, and text normalization in the locked decisions.
- Multi-file and multi-hunk input is flattened without sorting, grouping, or
  dropping rows.
- Empty unified-diff text returns `[]`.
- Parser/library failures are not hidden behind fallback behavior or custom
  exceptions.
- `unidiff` is the only new dependency, the strict project tooling remains
  enabled, and the generated lockfile agrees with project metadata.
- Tests exercise application mapping only and never invoke Git.

### Verification

```bash
uv sync --dev
uv run pytest tests/test_diff.py
uv run ruff check gitpane/diff.py tests/test_diff.py
uv run ruff format --check gitpane/diff.py tests/test_diff.py
uv run mypy gitpane/diff.py tests/test_diff.py
```

## Story 2: Locate the first change and print the diff summary

### Files

- Edit `gitpane/diff.py`.
- Edit `tests/test_diff.py`.

### Work

1. Add `first_change_index()` as a simple ordered scan over a `Sequence[Row]`.
2. Return the first add/remove index, including `0` when the first row is a
   change, and return `None` for empty or context-only input.
3. Add `main()` and its module guard. Read standard input once, call `parse()`,
   then print exactly the locked two-line summary.
4. Test first-change behavior for a leading change, context before a change,
   an all-context sequence, and an empty sequence.
5. Test `main()` in-process by replacing standard input and capturing standard
   output with pytest. Use a literal valid patch and assert the complete output;
   do not spawn Python or Git from the test.

### Acceptance criteria

- First-change indexes are zero-based and refer directly to the flat row list.
- Context rows are skipped, while either removal or addition is a change.
- No-change input returns and prints `None` without an exception.
- `uv run python -m gitpane.diff` accepts a unified diff on standard input and
  prints only the exact row-count and first-change lines.
- Importing `gitpane.diff` does not read input or print output.
- No CLI framework, Git integration, or UI behavior is introduced.

### Verification

```bash
uv run pytest tests/test_diff.py
uv run ruff check gitpane/diff.py tests/test_diff.py
uv run ruff format --check gitpane/diff.py tests/test_diff.py
uv run mypy gitpane/diff.py tests/test_diff.py
printf '%s\n' '--- a/example.txt' '+++ b/example.txt' '@@ -1,2 +1,2 @@' ' same' '-old' '+new' | uv run python -m gitpane.diff
```

The final command must print exactly:

```text
Rows: 3
First change: 1
```

## Story 3: Final cleanup and milestone verification

### Files

- Review and, only when a fix is required, edit `pyproject.toml`.
- Regenerate, but never hand-edit, `uv.lock` if metadata changed.
- Review and, only when a fix is required, edit `gitpane/diff.py`.
- Review and, only when a fix is required, edit `tests/test_diff.py`.

### Work

1. Review the complete Milestone 2 diff for accidental complexity, duplicated
   parsing, broad type suppressions, stale imports, debug output, and work
   outside this milestone's scope.
2. Confirm `PatchSet` remains the sole parser and the implementation has no
   speculative renderer, Git command, UI, or later-step abstraction.
3. Apply only fixes needed to satisfy this milestone, then run the complete
   project checks and the standard-input printing milestone once.
4. Confirm the dependency metadata and generated lockfile agree and that no
   cache, virtual-environment, coverage, or build artifacts are included in the
   intended diff.
5. Confirm `docs/workflow.md` and all other out-of-scope files remain untouched.
   Leave status-table updates and commits to the orchestrator as required by
   `docs/workflow.md`.

### Acceptance criteria

- All Milestone 2 story acceptance criteria hold together.
- The module remains the smallest clear implementation of unified-diff parsing,
  first-change lookup, and the stated printing milestone.
- The full existing and new test suite passes without testing Git itself.
- Ruff formatting/lint and strict mypy checks pass for the package and tests.
- The representative standard-input invocation prints the exact expected
  summary and no extra output.
- Only Milestone 2-owned implementation files are changed; generated/local
  artifacts are absent and the unrelated `docs/workflow.md` is untouched.
- No application, editor, UI, browser, or smoke process is booted.

### Verification

```bash
uv sync --dev
uv run ruff check gitpane tests
uv run ruff format --check gitpane tests
uv run mypy gitpane tests
uv run pytest
printf '%s\n' '--- a/example.txt' '+++ b/example.txt' '@@ -1,2 +1,2 @@' ' same' '-old' '+new' | uv run python -m gitpane.diff
git status --short
```


# Milestone 4: Basic Textual UI

## Goal

Implement Step 4 of `docs/design-spec.md`: a basic Textual application with
staged and unstaged file lists in a fixed-width left pane and a scrollable,
plain unified diff on the right. Selecting a row loads its full-context diff;
Space or the row's `[ ]` prefix stages/unstages the whole file; and `r`
refreshes repository status. The milestone is complete when the non-running
application logic is covered by unit tests and all project checks pass. Per
`docs/workflow.md`, launching the app and real-repository navigation,
stage/unstage, mouse, and smoke checks remain user-owned.

Repository baseline: Milestones 1 through 3 are complete. `gitpane.git`
provides repository discovery, status, full-context diff, stage, and unstage;
`gitpane.diff` provides `parse()` and `first_change_index()`; and the model
distinguishes staged and unstaged `FileEntry` values. There is no UI module,
stylesheet, UI test, or Textual dependency. The working tree is clean at plan
time.

## Scope boundary

### In scope

- Adding Textual as the sole new direct runtime dependency and regenerating the
  lockfile with `uv`.
- `gitpane/app.py` as the executable Textual application module and
  `gitpane/app.tcss` as its stylesheet.
- Two independently navigable `ListView` widgets, staged above unstaged, in one
  left `Vertical` fixed at exactly 30 columns.
- One right-side `VerticalScroll` containing one `Static` diff widget.
- Repository status loading on mount and on the `r` binding, preserving the
  order returned by `git.status()`.
- Selection loading through `git.diff()` followed by `diff.parse()`.
- Plain Rich `Text` row rendering with a marker, old/new line numbers, row text,
  and green/red backgrounds for additions/removals.
- Initial scrolling to the first add/remove row using
  `diff.first_change_index()`.
- Whole-file stage/unstage with Space on the focused list row or a mouse click
  on that row's literal `[ ]` prefix, followed by status refresh.
- Focused unit tests for pure/separable UI application logic without running a
  Textual event loop or invoking Git.

### Out of scope

- Syntax or language highlighting, reconstructed file content, or Step 5 work.
- File watching, automatic refresh, debounce behavior, selection restoration,
  diff caching, threading, or Step 6 work.
- Side-by-side display, hunk/line staging, commit support, conflicts, rename or
  binary handling, and changes to existing Git/diff/model behavior.
- Optimized `render_line`, virtualized/custom diff widgets, themes, dialogs,
  headers, footers, command palettes, help screens, notifications, or error
  recovery UI.
- Updating a diff in place after external changes. Every manual or mutation
  refresh may clear the current selection and right pane; Step 6 owns
  re-applying a surviving selection.
- Tests that call `App.run()`, `App.run_test()`, use a Pilot, start an event
  loop, invoke subprocesses/Git, create repositories, or perform terminal,
  browser, editor, app, or smoke checks.
- Changes to `gitpane/git.py`, `gitpane/diff.py`, `gitpane/model.py`,
  `gitpane/__init__.py`, existing tests, README, design spec, or workflow.

## Locked decisions

| Area | Decision |
| --- | --- |
| Dependencies | Add only `textual>=1.0.0` to `[project].dependencies` and regenerate `uv.lock` through `uv add`/`uv lock`; never hand-edit the lockfile. Do not add a Textual pytest plugin, snapshot package, watcher, or other direct dependency. Rich is already a required Textual dependency and is used only for Textual's `Text` renderable. |
| Module entry point | Create `gitpane/app.py` with `main() -> None` and an `if __name__ == "__main__"` guard. `main()` discovers the root with `git.repo_root()`, constructs the app with that explicit `Path`, and calls `run()`. Importing the module must not discover a repository, read status, or start Textual. Do not add a console-script entry point or re-export UI names. |
| Widget tree | Compose one horizontal body containing a left `Vertical` and a right `VerticalScroll`. The left container holds a plain `Static` heading and `ListView` for staged entries, then the same pair for unstaged entries. The right scroll contains exactly one `Static` used for the complete diff `Text`. Use stable IDs for the sidebar, both lists, scroll, and diff so handlers and TCSS do not depend on tree position. |
| Sizing | In `gitpane/app.tcss`, set the left `Vertical` width, minimum width, and maximum width to `30`; it must not grow or shrink. Let the right `VerticalScroll` consume the remaining width and scroll on both axes. Each file list shares available sidebar height. Do not calculate terminal widths in Python. |
| File item | Use one small `ListItem` subclass carrying its immutable `FileEntry`. Its visible, markup-disabled label is exactly `[ ] {status} {path}`. Do not truncate, quote, normalize, decorate, color, or syntax-highlight paths. The two lists contain only these items and retain `git.status()` ordering. |
| Refresh | On mount and from `r`, call `git.status(self.root)`, clear and repopulate both lists, set `selection` to `None`, clear the diff `Static`, and scroll the diff container to the origin. Focus and highlight the first staged entry, or the first unstaged entry when staged is empty; tolerate both lists being empty. Keep this synchronous Git work simple for the MVP—no worker or thread. |
| Selection | Store selection as `tuple[str, Side] | None`. `on_list_view_selected` obtains the selected item's `FileEntry`, assigns `(entry.path, entry.side)`, calls `git.diff(self.root, entry)`, passes that exact string to `diff.parse()`, renders all returned rows, and replaces the right `Static` content. Do not load a diff merely because refresh highlights the first row. Selecting either list uses the same path. |
| Initial diff position | After replacing the `Static`, reset the scroll to the origin. If `diff.first_change_index(rows)` returns an index, schedule a post-layout scroll to that zero-based row; otherwise remain at the origin. Do not add offsets for headers because the diff widget has none. |
| Plain row format | Build one Rich `Text` for all rows; do not use markup or `Syntax`. Render each row as `{marker} {old:>4} {new:>4} {text}`, where marker is `+`, `-`, or one space, and a missing number is four spaces. Separate rows with one newline and do not synthesize an additional row. Apply a green background to the complete addition row, a red background to the complete removal row, and no explicit style to context. Preserve `Row.text` exactly, including markup-looking characters and whitespace. |
| Keyboard toggle | Bind Space to one action. It acts only when a staged/unstaged `ListView` has focus and has a highlighted file item. Dispatch by `entry.side`: staged calls `git.unstage(self.root, entry.path)` and unstaged (including `?`) calls `git.stage(self.root, entry.path)`. If there is no focused item, do nothing. |
| Mouse toggle | A normal row click retains Textual's standard selection behavior and therefore loads its diff. Only a click whose item-local horizontal offset falls on columns `0`, `1`, or `2` (the literal `[ ]`) requests the same toggle for that clicked item's entry; stop that prefix click from also producing a stale selection load. Put the offset predicate in a tiny pure helper so boundary behavior can be tested without an app. Do not add a checkbox widget or separate per-row button. |
| Mutation result | After a successful stage/unstage, perform the same full refresh, clearing selection and diff. Let existing Git exceptions propagate; error dialogs/retry behavior are not part of this milestone. Never infer or manually move an item between lists. |
| Test seam | Keep only three small module-level helpers where they isolate logic from Textual: format the file label, load rows (`git.diff` then `diff.parse`), and dispatch stage/unstage. The row renderer and prefix-offset predicate are also directly testable functions. Do not introduce a controller, repository protocol, service class, or dependency-injection framework. |
| Testing | Create `tests/test_app.py`. Test helpers with literal `FileEntry`/`Row` values and monkeypatched module functions. Assertions cover exact labels and plain row output/style spans, diff-to-parser call order/data, side-based mutation dispatch, and prefix offset boundaries. Tests must not instantiate/run the application merely to inspect layout; widget composition and TCSS are verified by review, Ruff, mypy, and user-owned app checks. |

## Story execution rules

Each story must be dispatched with its specification, this milestone's scope
and locked decisions, exact paths, and the Required Coder-Prompt Rules from
`docs/workflow.md`: **Do NOT boot the editor/application or run any
browser/smoke test.** **NEVER use `git stash`, `git checkout --`, or `git
restore` on any file not intentionally edited for this task; if something
unexpected changes, stop and report it.** Escalate unresolved architectural
decisions to the senior coder rather than guessing. Use
`PYTHONDONTWRITEBYTECODE=1` for Python checks. A coder must not start another
story, commit, or update this status table.

## Story status

| Story | Title | Status |
| --- | --- | --- |
| 1 | Add Textual and compose the status panes | Complete |
| 2 | Load and render selected diffs | Complete |
| 3 | Add keyboard and prefix-click stage toggles | Complete |
| 4 | Final cleanup and milestone verification | Complete |

## Story 1: Add Textual and compose the status panes

### Files

- Edit `pyproject.toml`.
- Regenerate `uv.lock`; do not hand-edit it.
- Create `gitpane/app.py`.
- Create `gitpane/app.tcss`.
- Create `tests/test_app.py`.

### Work

1. Add the single locked direct dependency with `uv`, preserving all existing
   metadata, development dependencies, and tool settings.
2. Add the app class, explicit-root constructor, `CSS_PATH`, module `main()`,
   and guarded executable entry point. Importing the module must remain inert.
3. Compose the exact two-pane widget tree and add minimal TCSS that fixes the
   left pane at 30 columns, shares its height between the two lists, and gives
   the remaining scrollable area to the right pane. Add no visual chrome.
4. Add the file-item type and exact markup-disabled `[ ] STATUS PATH` label.
   Implement the label formatting as a pure helper.
5. Implement mount/manual status refresh and list replacement. Preserve model
   order, clear stale selection/diff/scroll state, and focus the first item from
   the first nonempty list without selecting/loading its diff.
6. Bind `r` to refresh. Do not add Space or mouse mutation behavior yet.
7. Add unit tests for exact file labels, including spaces, leading dashes, and
   markup-looking brackets in a path. Tests may call the pure helper only; do
   not start or pilot the app.

### Acceptance criteria

- `textual>=1.0.0` is the only new direct dependency and `uv.lock` matches the
  project metadata.
- `gitpane.app` imports without repository or UI side effects and exposes a
  guarded manual entry point.
- The composed UI has exactly two left `ListView`s and one right
  `VerticalScroll`/`Static`; TCSS fixes only the left container at 30 columns.
- Refresh populates staged and unstaged rows in returned order and handles
  either or both lists being empty.
- Labels are literal plain text and preserve paths; no diff loading, mutation,
  highlighting, watcher, or speculative abstraction is introduced.
- Tests do not boot Textual or invoke Git.

### Verification

```bash
uv sync --dev
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff check gitpane/app.py tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff format --check gitpane/app.py tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run mypy gitpane/app.py tests/test_app.py
git diff --check -- pyproject.toml uv.lock gitpane/app.py gitpane/app.tcss tests/test_app.py
git status --short
```

Do not run `python -m gitpane.app`, Textual devtools/console, `run_test()`, or an
app/browser/smoke command.

## Story 2: Load and render selected diffs

### Files

- Edit `gitpane/app.py`.
- Edit `tests/test_app.py`.

### Work

1. Add the locked row-loading helper that calls `git.diff(root, entry)` once
   and passes its unchanged output directly to `diff.parse()` once.
2. Add the plain renderer with the exact marker/number/text columns and row
   background styles. Build one `Text`, preserve row text literally, and do not
   import or use `Syntax`.
3. Handle `ListView.Selected` only for the file-item type. Save the exact
   `(path, side)` selection, load and render rows, replace the one diff
   `Static`, and reset/schedule scrolling according to
   `first_change_index()`.
4. Unit-test the loading seam with recording fakes, proving the entry/root and
   raw patch are forwarded in order and parsed rows are returned unchanged.
5. Unit-test mixed context/remove/add rendering, missing line numbers, literal
   markup-looking row text, empty rows, exact newline separation, and the
   presence/absence of red and green background spans. Call helpers directly;
   do not instantiate or run the app.

### Acceptance criteria

- Selecting an item from either list loads through the existing Git and parser
  APIs and records its path/side selection.
- The right side remains one `Static` inside one `VerticalScroll`, updated with
  one complete plain `Text` rather than one widget per row.
- Every row has the exact locked columns and background policy, with no syntax
  highlighting or alteration of row text.
- A loaded diff starts at its first changed row when one exists and at the
  origin otherwise.
- Focused tests prove loading and rendering logic without running Textual or
  Git, and Story 1 behavior remains intact.

### Verification

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff check gitpane/app.py tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff format --check gitpane/app.py tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run mypy gitpane/app.py tests/test_app.py
git diff --check -- gitpane/app.py tests/test_app.py
git status --short
```

Do not run `python -m gitpane.app`, `run_test()`, a Pilot, or any
app/browser/smoke check.

## Story 3: Add keyboard and prefix-click stage toggles

### Files

- Edit `gitpane/app.py`.
- Edit `tests/test_app.py`.

### Work

1. Add the locked mutation helper. Dispatch solely from `FileEntry.side`, pass
   the root/path unchanged, and return `None`; do not inspect status or mutate
   model/list values.
2. Bind Space and implement the focused-list/highlighted-item lookup. No focus
   or item is a no-op; otherwise mutate and run the same full refresh used by
   `r`.
3. Add the pure item-local prefix predicate for inclusive offsets `0..2` and
   connect the file item's click handler/message to mutate the clicked entry.
   A click outside the prefix must remain an ordinary ListView selection.
4. Ensure a prefix click cannot also finish a stale diff selection load, while
   keyboard and mouse paths share mutation dispatch and post-success refresh.
5. Unit-test stage and unstage dispatch with recording fakes, including an
   untracked entry, unchanged paths, successful `None`, and propagation of the
   same sentinel exception.
6. Unit-test prefix boundaries (`-1`, `0`, `2`, and `3`) directly. Do not
   fabricate Textual events or run/pilot an application.

### Acceptance criteria

- Space stages the highlighted unstaged item or unstages the highlighted
  staged item and safely does nothing without a focused highlighted file row.
- Clicking exactly the `[ ]` prefix toggles that clicked entry; clicking the
  rest of a row selects and loads its diff normally.
- Both toggle paths call only the existing whole-file Git APIs and perform a
  full successful refresh that clears stale selection/diff state.
- Paths and Git exceptions pass through unchanged; there is no optimistic list
  mutation, checkbox state, hunk behavior, or error UI.
- Unit tests cover dispatch and click-boundary application logic without
  invoking Git or booting Textual.

### Verification

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff check gitpane/app.py tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff format --check gitpane/app.py tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run mypy gitpane/app.py tests/test_app.py
git diff --check -- gitpane/app.py tests/test_app.py
git status --short
```

Do not execute real stage/unstage commands and do not run the app, `run_test()`,
a Pilot, browser, editor, or smoke check.

## Story 4: Final cleanup and milestone verification

### Files

- Review and, only when a milestone fix is required, edit `pyproject.toml`.
- Regenerate, but never hand-edit, `uv.lock` if metadata changed.
- Review and, only when a milestone fix is required, edit `gitpane/app.py`.
- Review and, only when a milestone fix is required, edit `gitpane/app.tcss`.
- Review and, only when a milestone fix is required, edit `tests/test_app.py`.
- Do not modify any other file; status-table updates and commits remain the
  orchestrator's responsibility.

### Work

1. Review the complete Milestone 4 diff for accidental complexity, duplicate
   refresh/mutation paths, stale imports, debug output, unnecessary widgets or
   dependencies, and work outside the scope boundary.
2. Confirm the final widget tree and stylesheet retain two ordered lists in an
   exactly 30-column left `Vertical` and one right
   `VerticalScroll`/`Static`, with no `render_line`, `Syntax`, watcher, or
   later-step behavior.
3. Confirm selection uses `git.diff()` then `diff.parse()`, first-change scroll
   uses the existing helper, and both mutation inputs use existing stage/
   unstage APIs followed by the shared refresh.
4. Confirm tests exercise only separable application logic with fakes and
   literals. They must not call app-running APIs, invoke Git/subprocesses,
   create a repository, or claim to verify Textual's own event behavior.
5. Apply only required fixes, then run the complete project checks once. Do not
   launch the module or substitute a terminal/browser/app smoke check.
6. Inspect the intended diff and status for generated/local artifacts or
   unrelated changes. Stop and report anything unexpected rather than using a
   destructive Git command.
7. Leave status-table updates and all commits to the orchestrator as required
   by `docs/workflow.md`.

### Acceptance criteria

- All Milestone 4 and prior acceptance criteria hold together.
- The UI remains the smallest clear Step 4 implementation: fixed two-list
  sidebar, one scrollable plain diff, selection loading, two toggle inputs, and
  manual refresh only.
- `textual` is the only new direct dependency and metadata/lockfile agree.
- Ruff formatting/lint, strict mypy, and the complete pytest suite pass.
- Tests prove GitPane's helper/application decisions without testing Git or
  running a Textual app/event loop.
- Only milestone-owned implementation/dependency files are changed; generated
  local artifacts and unrelated files are absent from the intended diff.
- No application, editor, terminal UI, browser, Pilot, or smoke process is
  booted, and no real stage/unstage operation is performed.

### Verification

```bash
uv sync --dev
PYTHONDONTWRITEBYTECODE=1 uv run ruff check gitpane tests
PYTHONDONTWRITEBYTECODE=1 uv run ruff format --check gitpane tests
PYTHONDONTWRITEBYTECODE=1 uv run mypy gitpane tests
PYTHONDONTWRITEBYTECODE=1 uv run pytest
git diff --check -- pyproject.toml uv.lock gitpane/app.py gitpane/app.tcss tests/test_app.py
git status --short
```

There is deliberately no `python -m gitpane.app`, `textual run`, `run_test()`,
Pilot, app, browser, or smoke verification command. The user owns the design
spec's real-repository navigation, mouse, diff-viewing, and stage/unstage
milestone check after implementation is complete.


# Milestone 5: Syntax-highlighted diffs

## Goal

Implement Step 5 of `docs/design-spec.md`: derive the selected file's new-side
source from parsed unified-diff rows, highlight it with Rich `Syntax`, and
project those styles back onto context and addition rows by their new-side line
numbers. Removal text remains plain while the existing red/green complete-row
diff backgrounds remain intact. The milestone is complete when this behavior,
including language selection from `FileEntry.path`, is covered entirely by
helper-level tests and all non-interactive project checks pass.

Repository baseline: Milestones 1 through 4 are complete. `gitpane/app.py`
already loads a selected `FileEntry` into a flat `list[Row]`, renders one Rich
`Text` with fixed marker/line-number columns, and applies complete-row change
backgrounds. Rich and Pygments are already transitive runtime requirements of
Textual, so no dependency or lockfile change is needed. The working tree has an
authorized uncommitted user documentation edit in `README.md`; every story
must leave it byte-for-byte untouched and must not treat it as milestone work.

## Scope boundary

### In scope

- Reconstructing new-side source by joining, with `\n`, the `text` of every
  context/add row in existing row order and excluding every removal row.
- Selecting a Rich/Pygments lexer from the selected `FileEntry.path` and the
  reconstructed source through Rich's existing lexer-selection API.
- Running the reconstructed source through Rich `Syntax.highlight()` once and
  splitting the resulting Rich `Text` into styled lines while preserving blank
  lines.
- Applying a highlighted line to each row that has `new_no`, using the
  one-based `new_no` as the index back into the reconstructed new side.
- Keeping removal row text free of syntax styles.
- Preserving the existing marker, old/new number columns, literal row text,
  newline behavior, green addition background, and red removal background.
- Passing the selected `FileEntry` into the renderer so its exact path drives
  language selection.
- Focused tests of module-level reconstruction, lexer/highlighting, and
  rendering helpers using literal `FileEntry`/`Row`/`Text` values and
  monkeypatches where isolation is useful.

### Out of scope

- Changes to Git commands, status parsing, unified-diff parsing, the model, or
  first-change scrolling.
- Highlighting removal text from the old file, reconstructing the old side, or
  loading either file directly from the filesystem.
- Per-hunk language detection, mixed-language regions, semantic parsing, custom
  lexers, a hand-maintained extension map, or a user-configurable language
  override.
- Changing Rich's default syntax theme, introducing a GitPane theme, changing
  diff background colors, or syntax-highlighting the gutter/line numbers.
- File watching, automatic refresh, selection restoration, caching,
  virtualization, threading/workers, performance redesign, or Step 6 work.
- Side-by-side display, hunk/line staging, commit support, conflicts, renames,
  binary-file support, and other post-MVP behavior.
- Adding or changing direct dependencies, project metadata, the lockfile,
  stylesheet, package initializer, or documentation other than appending this
  Milestone 5 plan.
- Any test that constructs or runs `GitPaneApp`, calls `App.run()` or
  `App.run_test()`, uses a Pilot/event loop, invokes Git/subprocesses, creates a
  repository, or performs an app, terminal UI, editor, browser, or smoke check.
- Editing, reverting, staging, formatting, or otherwise touching the
  authorized uncommitted `README.md` change.

## Locked decisions

| Area | Decision |
| --- | --- |
| Owned implementation files | Milestone implementation edits only `gitpane/app.py` and `tests/test_app.py`. `gitpane/diff.py`, `gitpane/model.py`, `gitpane/git.py`, `gitpane/app.tcss`, `gitpane/__init__.py`, `pyproject.toml`, and `uv.lock` remain unchanged. |
| Reconstruction helper | Add `reconstruct_new_source(rows: Sequence[Row]) -> str` in `gitpane/app.py`. Select rows whose kind is not `"remove"` and join their exact `Row.text` values with one `\n` in row order. Do not use `old_no`, read the working tree, append an unconditional trailing newline, dedent, expand tabs, or strip whitespace. An empty/all-removal sequence returns `""`; a retained row whose text is empty still represents a real blank line. |
| Language selection | Add a small `lexer_for_entry(entry: FileEntry, source: str) -> str` helper that calls `Syntax.guess_lexer(entry.path, source)` with the exact repository-relative path and reconstructed source and returns its result unchanged. This uses Rich's bundled Pygments filename/content knowledge for extensions, special filenames, and case handling without a new dependency or local mapping. Rich's `"default"` result is the robust plain-text fallback for an unknown or extensionless unmatched path; do not guess from `Path.suffix`, catch broad exceptions, or default unknown files to a specific programming language. |
| Highlighting helper | Add `highlight_new_lines(entry: FileEntry, rows: Sequence[Row]) -> list[Text]`. Materialize the non-removal rows once so an empty/all-removal input can return `[]` without manufacturing a source line. Otherwise reconstruct the source, select the lexer once, construct one `Syntax(source, lexer)` with Rich defaults, call its public `highlight(source)` once, and split the returned `Text` on `"\n"` with blank lines retained. Ignore only a lexer-produced trailing split line that no row indexes; do not flatten styles to markup/ANSI strings or invoke one `Syntax` per row. |
| New-side indexing | The renderer looks up syntax text only when `row.new_no is not None`, at `highlighted_lines[row.new_no - 1]`. This is deliberately one-based new-file indexing, not display-row or non-removal-list indexing; a removal interleaved before an addition must not shift the addition's syntax line. The existing full-context diff contract supplies the complete ordered new side and valid line numbers, so do not add a sparse-line remapping model or silently substitute neighboring styles. |
| Renderer API | Change the helper signature to `render_diff_rows(entry: FileEntry, rows: list[Row]) -> Text`, and update the one selection-handler call site to pass the same selected entry used to load the rows. Do not store a lexer/language on `FileEntry`, `Row`, or application state. |
| Row composition | Continue to build one complete Rich `Text`. Append the existing plain gutter (`marker`, old number, new number, and separating space) and then append the corresponding highlighted line for context/add rows. Append `row.text` as plain text for removals. The resulting `.plain` value must be exactly the Milestone 4 output, including literal markup-looking text, whitespace, empty rows, and one separator newline between rows only. |
| Style precedence | Preserve Rich syntax foreground styles on context/add text only. After composing each complete row, apply the existing green background to the complete addition row or red background to the complete removal row so diff backgrounds win over any syntax-theme background without discarding syntax foregrounds. Context rows receive no diff background. Gutter text receives no syntax token style. |
| Removal policy | A row with `new_no is None` never indexes highlighted output. In particular, removals remain plain foreground text even when their content resembles source code; their only explicit style remains the existing complete-row red background. This intentional MVP limitation is not an error fallback. |
| Testing seam | Tests call only `reconstruct_new_source`, `lexer_for_entry`, `highlight_new_lines`, and `render_diff_rows`. Use monkeypatching/controlled Rich `Text` values to prove call inputs and line-number projection without depending on a particular Pygments color palette. Do not instantiate `FileItem`, compose widgets, fabricate Textual events, or construct/run `GitPaneApp`. |
| Dependencies | Import `Syntax` from `rich.syntax` and `Sequence` from `collections.abc`; Rich/Pygments already arrive through Textual. Do not add Rich or Pygments as a new direct dependency and do not regenerate `uv.lock`. |

## Story execution rules

Each story must be dispatched with its specification, this milestone's scope
and locked decisions, exact paths, and the Required Coder-Prompt Rules from
`docs/workflow.md`: **Do NOT boot the editor/application or run any
browser/smoke test.** **NEVER use `git stash`, `git checkout --`, or `git
restore` on any file not intentionally edited for this task; if something
unexpected changes, stop and report it.** Escalate unresolved architectural
decisions to the senior coder rather than guessing. Use
`PYTHONDONTWRITEBYTECODE=1` for Python checks. A coder must not start another
story, commit, update this status table, or touch `README.md`. Verification must
not invoke Git, Textual app-running APIs, a Pilot, or a subprocess-based smoke
test.

## Story status

| Story | Title | Status |
| --- | --- | --- |
| 1 | Reconstruct and highlight the new side | Complete |
| 2 | Project syntax styles into rendered diff rows | Not started |
| 3 | Final cleanup and milestone verification | Not started |

## Story 1: Reconstruct and highlight the new side

### Files

- Edit `gitpane/app.py`.
- Edit `tests/test_app.py`.
- Do not edit `README.md` or any other file.

### Work

1. Import `Sequence` and Rich `Syntax`, then add the three locked helpers:
   `reconstruct_new_source`, `lexer_for_entry`, and `highlight_new_lines`.
   Keep them module-level and functional; do not introduce a highlighter class,
   protocol, cache, or application state.
2. Reconstruct source from context/add row text only. Preserve source ordering,
   empty lines, indentation, tabs, trailing spaces, and markup-looking text;
   only the join separators are synthesized.
3. Pass the exact `FileEntry.path` and reconstructed source to
   `Syntax.guess_lexer`. Retain Rich's `default` fallback rather than adding
   extension aliases or special cases in GitPane.
4. For a source containing at least one non-removal row, instantiate one
   `Syntax` and call `highlight(source)` once. Split the returned Rich `Text`
   with blank lines retained so token spans stay attached to their individual
   lines. Return `[]` for empty/all-removal rows without calling the lexer or
   highlighter.
5. Add helper-level tests for reconstruction covering mixed context/removal/
   addition rows, an empty retained row, whitespace, and empty/all-removal
   input. Assert removals contribute neither content nor an extra separator.
6. Add a helper-level language-selection test that monkeypatches
   `Syntax.guess_lexer`, records the exact path and source, and proves the Rich
   result is forwarded unchanged. Include a repository-relative path with
   directories, spaces, and an uppercase extension; do not assert a
   Pygments-version-specific lexer choice.
7. Add helper-level highlighting tests with monkeypatched Rich seams that prove
   one reconstructed source/lexer/highlight pass, retained blank styled lines,
   and no work for all-removal input. Assert returned objects remain Rich
   `Text`, not plain/markup/ANSI conversions.
8. Do not alter `render_diff_rows` or its selection-handler call in this story;
   renderer integration belongs to Story 2.

### Acceptance criteria

- Reconstruction is exactly `\n`.join of all and only non-removal `Row.text`
  values in existing order, with source whitespace unchanged.
- Language selection receives the exact selected entry path and complete
  reconstructed source and relies solely on Rich's robust built-in selection
  and plain default fallback.
- Highlighting performs one whole-new-side Rich `Syntax` pass, preserves Rich
  line styles and blank lines, and returns no lines for an all-removal/empty
  sequence.
- No filesystem read, Git call, per-row lexer pass, dependency/metadata change,
  widget/app construction, or out-of-scope abstraction is introduced.
- New tests are helper-level only and do not run Textual, Pilot, Git, a browser,
  or a smoke process.
- `README.md` remains exactly as found.

### Verification

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff check gitpane/app.py tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff format --check gitpane/app.py tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run mypy gitpane/app.py tests/test_app.py
```

Do not run `python -m gitpane.app`, `textual run`, `run_test()`, a Pilot, Git,
or any terminal/app/browser/smoke command.

## Story 2: Project syntax styles into rendered diff rows

### Files

- Edit `gitpane/app.py`.
- Edit `tests/test_app.py`.
- Do not edit `README.md` or any other file.

### Work

1. Change `render_diff_rows` to accept the selected `FileEntry` before `rows`
   and obtain highlighted new-side lines from the Story 1 helper exactly once.
2. Preserve the existing gutter format and newline assembly. For each row with
   `new_no`, append `highlighted_lines[new_no - 1]` as Rich `Text`; for a
   removal, append its exact `row.text` as plain text without consulting the
   highlighted lines.
3. Apply the existing addition/removal background to the full row only after
   gutter and content composition. Ensure this overlays a Syntax theme
   background while retaining syntax foreground styles on addition text.
   Context rows remain free of diff background and all gutter characters
   remain free of syntax token styles.
4. Update `on_list_view_selected` to call `render_diff_rows(entry, rows)` with
   the exact entry already passed to `load_diff_rows`. Make no other event,
   selection, refresh, scrolling, or mutation change.
5. Update the existing renderer tests for the new signature while retaining
   their exact `.plain`, line-number, markup-literal, blank-row, newline, and
   complete-row-background assertions.
6. Add a helper-level renderer test that replaces `highlight_new_lines` with
   controlled differently styled Rich lines. Use context/add rows with
   meaningful `new_no` values and an interleaved removal to prove lookup is by
   `new_no - 1`, not display index. Assert syntax foreground is confined to
   context/add content, never the gutter or removal text.
7. In the same focused assertions, prove the full addition retains green
   background in combination with its syntax foreground, the full removal is
   red with plain foreground, and context receives syntax style without a diff
   background. Avoid assertions tied to Rich's default theme colors by using
   the controlled helper result.
8. Do not instantiate or run the app to test the updated event call. Establish
   the one straightforward call-site change by code review and static checks,
   consistent with the existing Milestone 4 testing boundary.

### Acceptance criteria

- Selecting an entry passes that same `FileEntry` into rendering, so its exact
  path determines the lexer without new model/application state.
- Rendered plain output is byte-for-text identical to Milestone 4 for the same
  rows.
- Every context/add row displays the highlighted line selected by its one-based
  `new_no`; interleaved removals do not shift that lookup.
- Removal content is syntax-plain, while complete-row red/green backgrounds and
  syntax foreground on additions coexist with the locked precedence.
- Gutter text is never syntax-highlighted, and scrolling, toggling, refresh,
  and diff loading behavior are unchanged.
- Tests exercise renderer/helper behavior only; they do not construct or run
  Textual, use a Pilot, invoke Git/subprocesses, or perform smoke checks.
- `README.md` and every non-owned implementation file remain untouched.

### Verification

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff check gitpane/app.py tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run ruff format --check gitpane/app.py tests/test_app.py
PYTHONDONTWRITEBYTECODE=1 uv run mypy gitpane/app.py tests/test_app.py
```

Do not run `python -m gitpane.app`, `textual run`, `run_test()`, a Pilot, Git,
or any terminal/app/browser/smoke command.

## Story 3: Final cleanup and milestone verification

### Files

- Review and, only when a Milestone 5 fix is required, edit
  `gitpane/app.py`.
- Review and, only when a Milestone 5 fix is required, edit
  `tests/test_app.py`.
- Do not modify `README.md`, dependency files, documentation, or any other
  source/test file; status-table updates and commits remain the orchestrator's
  responsibility.

### Work

1. Review the complete Milestone 5 implementation for the exact reconstruction
   rule, one Rich `Syntax` pass, Rich-based path/language selection, direct
   `new_no - 1` projection, plain removals, and preserved row backgrounds.
2. Remove only accidental milestone complexity such as a local extension map,
   duplicate highlighting passes, per-row `Syntax` construction, style-to-
   markup conversion, filesystem reads, broad exception handling, caches,
   speculative watcher behavior, stale imports, or debug output.
3. Confirm the renderer's `.plain` contract and all Milestone 4 selection,
   scrolling, refresh, and mutation code remain unchanged except for passing
   the selected entry into the renderer.
4. Confirm every new/changed test calls module-level helpers only and uses
   literals or monkeypatches. It must not instantiate widgets/the app, fabricate
   UI events, start an event loop/Pilot, invoke Git/subprocesses, create a
   repository, or claim to verify Rich/Pygments internals.
5. Apply only fixes needed for this milestone, then run the complete static and
   unit-test checks below once with bytecode writing disabled. Do not add a
   manual app, Git, browser, terminal UI, or smoke verification step.
6. Review the intended owned-file changes through the available non-destructive
   orchestration context. The authorized `README.md` edit must remain untouched;
   stop and report any other unexpected change rather than trying to clean it
   with Git commands.
7. Leave status-table updates and all commits to the orchestrator as required
   by `docs/workflow.md`.

### Acceptance criteria

- All Milestone 5 and prior helper-level acceptance criteria hold together.
- The implementation is the smallest clear Step 5 extension: three small
  helpers, one entry-aware renderer, and one updated call site, with no custom
  language registry or later-milestone machinery.
- Rich `Syntax` highlights one reconstructed new side and styles are projected
  by `new_no`; removals remain syntax-plain and diff backgrounds are preserved.
- Ruff formatting/lint, strict mypy, and the complete pytest suite pass.
- Tests remain helper-level and no app/Pilot/event loop, Git/subprocess,
  repository, browser, editor, terminal UI, or smoke process is run.
- Only `gitpane/app.py` and `tests/test_app.py` are implementation changes for
  this milestone. Dependency metadata and lockfile remain unchanged, and the
  pre-existing `README.md` edit remains untouched.

### Verification

```bash
PYTHONDONTWRITEBYTECODE=1 uv run ruff check gitpane tests
PYTHONDONTWRITEBYTECODE=1 uv run ruff format --check gitpane tests
PYTHONDONTWRITEBYTECODE=1 uv run mypy gitpane tests
PYTHONDONTWRITEBYTECODE=1 uv run pytest
```

There is deliberately no dependency sync, Git command, `python -m gitpane.app`,
`textual run`, `run_test()`, Pilot, app, terminal UI, editor, browser, or smoke
verification command. The user owns visual confirmation after implementation.
