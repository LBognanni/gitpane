import asyncio
from pathlib import Path

import pytest
from rich.text import Text
from textual.content import Content
from textual.widgets import Static, TabbedContent, Tree

from gitpane.app import GitPaneApp
from gitpane.model import RepoState
from gitpane.preview import MAX_PREVIEW_BYTES, PreviewView, load_preview_view
from gitpane.widgets import CodeView, scrollbar_click_target


def test_load_preview_view_builds_numbered_highlighted_lines(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text("answer = 42\n")

    view = load_preview_view(path)

    assert isinstance(view, PreviewView)
    assert [line.plain for line in view.lines] == [" 1 answer = 42", " 2 "]
    assert view.lines[0].spans
    assert view.lines[0].style == ""
    assert view.lines[0].spans[0].start == 0
    assert view.lines[0].spans[0].end == 3
    assert view.lines[0].spans[0].style == "dim"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("", [" 1 "]),
        ("first", [" 1 first"]),
        ("first\n", [" 1 first", " 2 "]),
        ("first\n\n", [" 1 first", " 2 ", " 3 "]),
        ("first\rsecond", [" 1 first", " 2 second"]),
        ("first\r\nsecond", [" 1 first", " 2 second"]),
    ],
)
def test_load_preview_view_preserves_logical_lines(
    tmp_path: Path, source: str, expected: list[str]
) -> None:
    path = tmp_path / "example.txt"
    path.write_text(source)

    view = load_preview_view(path)

    assert [line.plain for line in view.lines] == expected


@pytest.mark.parametrize(
    ("name", "contents", "message"),
    [
        ("binary.dat", b"before\0after", "Binary files cannot be previewed."),
        ("invalid.txt", b"\xff", "File is not valid UTF-8."),
        (
            "large.txt",
            b"x" * (MAX_PREVIEW_BYTES + 1),
            "File is too large to preview (maximum 1 MiB).",
        ),
    ],
)
def test_load_preview_view_returns_friendly_messages(
    tmp_path: Path, name: str, contents: bytes, message: str
) -> None:
    path = tmp_path / name
    path.write_bytes(contents)

    view = load_preview_view(path)

    assert view.lines == (Text(message),)


def test_load_preview_view_handles_disappeared_file(tmp_path: Path) -> None:
    view = load_preview_view(tmp_path / "gone.txt")

    assert view.lines == (Text("File is no longer available."),)


def test_load_preview_view_handles_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "unreadable.txt"
    path.write_text("contents")

    def deny_open(*_: object, **__: object) -> object:
        raise PermissionError

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", deny_open)
        view = load_preview_view(path)

    assert view.lines == (Text("File could not be read."),)


def test_load_preview_view_rejects_non_regular_files(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("outside the selected path")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    view = load_preview_view(link)

    assert view.lines == (Text("Only regular files can be previewed."),)


def test_file_selection_shows_repository_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "nested" / "[bold]report.txt"
    path.parent.mkdir()
    path.write_text("answer = 42\n")
    monkeypatch.setattr(
        "gitpane.app.git.status", lambda root: RepoState(root, [], [], "main")
    )
    monkeypatch.setattr("gitpane.app.git.commits", lambda _: [])
    monkeypatch.setattr("gitpane.app.git.files", lambda _: ["nested/[bold]report.txt"])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            tree = app.query_one("#files-tree", Tree)
            tree.select_node(tree.root.children[0].children[0])
            await app.workers.wait_for_complete()
            await pilot.pause()

            title = app.query_one("#preview-title", Static)
            rendered_title = title.render()
            assert isinstance(rendered_title, Content)
            assert rendered_title.plain == "nested/[bold]report.txt"
            assert rendered_title.spans == []

    asyncio.run(exercise())


def test_loaded_preview_uses_current_wrap_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            app.query_one("#main-tabs", TabbedContent).active = "files-tab"
            await pilot.press("w")
            await pilot.pause()

            app.file_browser.apply_preview(
                PreviewView((Text(" 1 value = 1"),)),
                app.file_browser.preview_request_id,
            )

            preview = app.query_one("#preview-view", CodeView)
            assert preview.wrapped is True
            assert preview.lines == (Text(" 1 value = 1"),)

    asyncio.run(exercise())


def test_file_preview_scrollbar_track_click_jumps_to_clicked_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gitpane.app.git.status", lambda root: RepoState(root, [], []))
    monkeypatch.setattr("gitpane.app.git.files", lambda _: [])

    async def exercise() -> None:
        app = GitPaneApp(tmp_path)
        async with app.run_test() as pilot:
            app.query_one("#main-tabs", TabbedContent).active = "files-tab"
            scroll = app.query_one("#preview-view", CodeView)
            scroll.set_document(tuple(Text(str(number)) for number in range(1000)))
            await pilot.pause()

            scrollbar = scroll.vertical_scrollbar
            click_y = scrollbar.size.height * 3 // 4
            expected = scrollbar_click_target(
                click_y,
                scrollbar.size.height,
                scrollbar.window_virtual_size,
                scrollbar.window_size,
            )

            assert await pilot.click(scrollbar, offset=(0, click_y))
            await pilot.pause()

            assert scroll.scroll_y == pytest.approx(expected)

    asyncio.run(exercise())
