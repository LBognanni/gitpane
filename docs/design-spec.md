MVP scope

In: two file lists (staged/unstaged), stage/unstage, unified diff of the selected entry with syntax highlighting, full-file context scrolled to first change, mouse, file watching.

Out: side-by-side, commit, caching, threading, hunk/line staging, conflicts, renames, binary files.

Target: ~500 lines across 5 files.

Step 1 — model.py
python
class Side(Enum): STAGED, UNSTAGED

@dataclass(frozen=True)
class FileEntry:
    path: str
    side: Side
    status: str          # 'M', 'A', 'D', '?'

@dataclass
class RepoState:
    root: Path
    staged: list[FileEntry]
    unstaged: list[FileEntry]

A file modified in both index and worktree produces two entries, one in each list. That falls out of porcelain v2's separate X and Y codes — no special casing.

Step 2 — git.py

One _run() helper that sets cwd=root and GIT_OPTIONAL_LOCKS=0, then:

repo_root() → rev-parse --show-toplevel
status() → status --porcelain=v2 -z --untracked-files=all, split on \0, handle 1 (ordinary), ? (untracked), 2 (rename/copy), and u (unmerged) records; mark rename/copy and unmerged entries as visible but unsupported
diff(entry) → --cached -U9999 for staged, plain -U9999 for unstaged; both with --no-color --no-ext-diff
stage(path) / unstage(path)

Untracked files: return git diff --no-index -U9999 -- /dev/null <path> and swallow its exit code 1. That way everything downstream is a unified diff, with no "untracked" branch in the renderer.

Milestone: python -m gitpane.git prints parsed status for a real repo.

Step 3 — diff.py

unidiff.PatchSet → flat list[Row]:

python
Row = namedtuple("Row", "old_no new_no text kind")  # context|add|remove

Plus first_change_index(rows) for the initial scroll. That's the whole module — unified only, so no alignment algorithm needed yet.

Milestone: prints row counts and the index of the first change.

Step 4 — app.py + app.tcss

Two ListViews in a left Vertical (fixed 30 cols), a VerticalScroll on the right holding one Static. Skip render_line for now — a Static with the full Text is fine when you're not optimizing.

Wire up:

on_list_view_selected → set self.selection = (path, side), load diff
space / click a [ ] prefix → stage or unstage depending on which list has focus
r → manual refresh
Textual gives you mouse, scrolling, and focus for free

Rendering a row: +/-/ marker, line numbers, then the text with a green/red background style. Highlighting comes next step — for now, plain.

Milestone: navigate a real repo, stage and unstage, see diffs.

Step 5 — highlighting

Reconstruct the "new" side of the file by joining every non-remove row, run it through rich.syntax.Syntax(...).highlight(), split on newlines, and index back into it by new_no. Rows without a new_no (removals) fall back to plain text — imperfect, and invisible enough for an MVP.

Milestone: diffs are coloured by language.

Step 6 — watcher.py
python
@work(exclusive=True)
async def watch(self):
    async for _ in awatch(root, debounce=200):
        self.refresh_status()

Filter to skip .git/ except .git/index. On refresh, rebuild both lists and re-apply self.selection; if that entry is gone, clear the right pane. Don't reload the diff if the row list is unchanged.

Milestone: git add in another terminal updates the UI within ~200ms.
