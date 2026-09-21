"""Filesystem watching that reports repository invalidations."""

import asyncio
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from pathlib import Path

from watchfiles import awatch

from gitpane import git

DEBOUNCE_MS = 250


@dataclass(frozen=True)
class Invalidation:
    """What a batch of filesystem events made stale."""

    status: bool = False
    history: bool = False
    changed_paths: frozenset[Path] = frozenset()
    index_changed: bool = False

    def merge(self, other: "Invalidation") -> "Invalidation":
        """Return an invalidation covering both *self* and *other*."""
        return Invalidation(
            self.status or other.status,
            self.history or other.history,
            self.changed_paths | other.changed_paths,
            self.index_changed or other.index_changed,
        )


def classify(
    root: Path, git_dir: Path, common_dir: Path, paths: Iterable[Path]
) -> Invalidation:
    """Classify changed absolute *paths* for the worktree at *root*.

    ``changed_paths`` holds worktree paths relative to *root*. Only the index,
    HEAD, refs and packed refs are relevant below the Git directories.
    """
    result = Invalidation()
    for path in paths:
        if path.is_relative_to(git_dir):
            name = path.relative_to(git_dir)
            if name == Path("index"):
                result = result.merge(Invalidation(status=True, index_changed=True))
                continue
            if name == Path("HEAD"):
                result = result.merge(Invalidation(status=True, history=True))
                continue
        if path.is_relative_to(common_dir):
            name = path.relative_to(common_dir)
            if name == Path("packed-refs") or name.parts[:1] == ("refs",):
                result = result.merge(Invalidation(status=True, history=True))
            continue
        if path == root / ".git":
            continue
        if path.is_relative_to(root):
            result = result.merge(
                Invalidation(
                    status=True, changed_paths=frozenset({path.relative_to(root)})
                )
            )
    return result


async def watch(root: Path) -> AsyncIterator[Invalidation]:
    """Yield debounced invalidations for the repository at *root*.

    Setup failures such as ``OSError`` propagate to the caller.
    """
    git_dir, common_dir = await asyncio.to_thread(git.git_dirs, root)
    roots = {root}
    roots.update(d for d in (git_dir, common_dir) if not d.is_relative_to(root))
    # The default filter drops any path containing ".git" (and cache dirs),
    # which would hide the metadata events; classify() is the only filter.
    async for changes in awatch(*roots, debounce=DEBOUNCE_MS, watch_filter=None):
        invalidation = classify(
            root, git_dir, common_dir, (Path(path) for _, path in changes)
        )
        if invalidation != Invalidation():
            yield invalidation
