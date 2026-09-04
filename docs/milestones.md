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
| 3 | Final cleanup and milestone verification | Pending |

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
