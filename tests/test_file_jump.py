import asyncio
from pathlib import Path

import pytest
from textual.widgets import Input, OptionList, TabbedContent, Tree

from gitpane.app import FileJumpScreen, GitPaneApp, matching_files
from gitpane.model import RepoState
from gitpane.widgets import CodeView


def test_matching_files_requires_three_characters_and_matches_case_insensitively() -> (
    None
):
    files = (
        (Path("docs/Report.md"), "docs/report.md"),
        (Path("src/reporting.py"), "src/reporting.py"),
        (Path("src/other.py"), "src/other.py"),
    )

    assert matching_files(files, "re") == ((), False)
    assert matching_files(files, "REP") == (
        (Path("docs/Report.md"), Path("src/reporting.py")),
        False,
    )
    assert matching_files(files, "REPO") == (
        (Path("docs/Report.md"), Path("src/reporting.py")),
        False,
    )


def test_matching_files_reports_only_actual_truncation() -> None:
    hundred = tuple(
        (Path(f"match-{index}.txt"), f"match-{index}.txt") for index in range(100)
    )

    matches, truncated = matching_files(hundred, "match")
    assert len(matches) == 100
    assert truncated is False

    matches, truncated = matching_files(
        (*hundred, (Path("match-extra.txt"), "match-extra.txt")), "match"
    )
    assert len(matches) == 100
    assert truncated is True


def test_quick_file_jump_is_memory_backed_and_reveals_nested_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = Path("src/reports") / f"summary-{'x' * 80}.py"
    summer = Path("src/reports") / f"summer-{'y' * 80}.py"
    nested = tmp_path / summary
    nested.parent.mkdir(parents=True)
    nested.write_text("answer = 42\n")
    file_calls: list[Path] = []

    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])

    def fake_files(cwd: Path) -> list[str]:
        file_calls.append(cwd)
        return ["README.md", str(summary), str(summer)]

    monkeypatch.setattr("gitpane.app.git.files", fake_files)

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test(size=(100, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.press("t")
            assert not isinstance(app.screen, FileJumpScreen)

            await pilot.press("2")
            tree = app.query_one("#files-tree", Tree)
            tabs_region = app.query_one("#main-tabs", TabbedContent).region
            tree.loading = True
            await pilot.press("t")
            assert not isinstance(app.screen, FileJumpScreen)
            tree.loading = False

            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, FileJumpScreen)
            assert isinstance(app.screen.focused, Input)
            assert app.query_one("#main-tabs", TabbedContent).region == tabs_region
            dialog = app.screen.query_one("#file-jump-dialog")
            search_input = app.screen.query_one("#file-jump-input", Input)
            assert dialog.region.y == 3
            initial_height = dialog.region.height
            assert dialog.region.y <= search_input.region.y
            assert search_input.region.bottom <= dialog.region.bottom

            await pilot.press("s", "u")
            assert app.screen.query_one(OptionList).option_count == 0
            await pilot.press("m")
            await app.screen.workers.wait_for_complete()
            await pilot.pause()
            results = app.screen.query_one(OptionList)
            assert results.option_count == 2
            assert results.region.height > results.option_count
            assert results.max_scroll_y == 0
            assert dialog.region.height > initial_height
            assert file_calls == [tmp_path]

            await pilot.press("enter")
            await pilot.pause()

            assert not isinstance(app.screen, FileJumpScreen)
            target = app.file_nodes[summary]
            reports = target.parent
            assert reports is not None
            src = reports.parent
            assert src is not None
            assert tree.cursor_node is target
            assert tree.has_focus
            assert src.is_expanded
            assert reports.is_expanded
            await app.workers.wait_for_complete()
            await pilot.pause()
            preview = app.query_one("#preview-view", CodeView)
            assert "answer = 42" in "\n".join(
                preview.render_line(y).text for y in range(preview.size.height)
            )
            assert file_calls == [tmp_path]

            await pilot.press("t")
            assert isinstance(app.screen, FileJumpScreen)
            assert await pilot.click(app.screen, offset=(0, 0))
            await pilot.pause()
            assert not isinstance(app.screen, FileJumpScreen)
            assert tree.cursor_node is target

            await pilot.press("t")
            assert isinstance(app.screen, FileJumpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, FileJumpScreen)
            assert tree.cursor_node is target

    asyncio.run(exercise())
