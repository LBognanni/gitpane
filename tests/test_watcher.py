from pathlib import Path

from gitpane.watcher import Invalidation, classify

ROOT = Path("/work/repo")
NORMAL = (ROOT / ".git", ROOT / ".git")
LINKED_ROOT = Path("/work/linked")
LINKED = (Path("/work/repo/.git/worktrees/linked"), Path("/work/repo/.git"))


def test_worktree_edit_invalidates_status_with_relative_path() -> None:
    result = classify(ROOT, *NORMAL, [ROOT / "src" / "a.py"])

    assert result == Invalidation(
        status=True, changed_paths=frozenset({Path("src/a.py")})
    )


def test_index_change_invalidates_status_and_index() -> None:
    result = classify(ROOT, *NORMAL, [ROOT / ".git" / "index"])

    assert result == Invalidation(status=True, index_changed=True)


def test_head_refs_and_packed_refs_invalidate_status_and_history() -> None:
    for name in ("HEAD", "refs/heads/main", "packed-refs"):
        result = classify(ROOT, *NORMAL, [ROOT / ".git" / name])

        assert result == Invalidation(status=True, history=True), name


def test_other_git_metadata_is_ignored() -> None:
    paths = [
        ROOT / ".git" / "logs" / "HEAD",
        ROOT / ".git" / "objects" / "ab" / "cdef",
        ROOT / ".git" / "index.lock",
        ROOT / ".git" / "config",
    ]

    assert classify(ROOT, *NORMAL, paths) == Invalidation()


def test_linked_worktree_splits_metadata_between_directories() -> None:
    git_dir, common_dir = LINKED

    index = classify(LINKED_ROOT, *LINKED, [git_dir / "index"])
    head = classify(LINKED_ROOT, *LINKED, [git_dir / "HEAD"])
    ref = classify(LINKED_ROOT, *LINKED, [common_dir / "refs" / "heads" / "main"])
    packed = classify(LINKED_ROOT, *LINKED, [common_dir / "packed-refs"])

    assert index == Invalidation(status=True, index_changed=True)
    assert head == Invalidation(status=True, history=True)
    assert ref == Invalidation(status=True, history=True)
    assert packed == Invalidation(status=True, history=True)


def test_linked_worktree_ignores_other_metadata_and_git_file() -> None:
    git_dir, common_dir = LINKED
    paths = [
        LINKED_ROOT / ".git",
        git_dir / "logs" / "HEAD",
        common_dir / "index",
        common_dir / "HEAD",
        common_dir / "objects" / "ab",
    ]

    assert classify(LINKED_ROOT, *LINKED, paths) == Invalidation()


def test_paths_outside_repository_are_ignored() -> None:
    assert classify(ROOT, *NORMAL, [Path("/elsewhere/file")]) == Invalidation()


def test_batch_and_merge_combine_invalidations() -> None:
    batch = classify(
        ROOT, *NORMAL, [ROOT / "a.txt", ROOT / ".git" / "index", ROOT / ".git" / "HEAD"]
    )
    merged = batch.merge(Invalidation(changed_paths=frozenset({Path("b.txt")})))

    assert merged == Invalidation(
        status=True,
        history=True,
        changed_paths=frozenset({Path("a.txt"), Path("b.txt")}),
        index_changed=True,
    )
