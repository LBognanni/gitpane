import math
import re
from pathlib import Path

import pytest
from rich.style import Style

from gitpane.app import render_diff_rows
from gitpane.diff import Row
from gitpane.model import FileEntry, Side

STYLESHEET = Path(__file__).resolve().parents[1] / "gitpane" / "app.tcss"


def _stylesheet() -> str:
    return STYLESHEET.read_text()


def _variables(stylesheet: str) -> dict[str, str]:
    return dict(re.findall(r"^\$(\S+):\s*(#[0-9a-f]{6});$", stylesheet, re.MULTILINE))


def _rule(stylesheet: str, selector: str) -> str:
    match = re.search(
        rf"^{re.escape(selector)}\s*\{{(?P<body>.*?)^\}}",
        stylesheet,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing TCSS rule for {selector}"
    return match.group("body")


def _has_declaration(rule: str, declaration: str) -> bool:
    return re.search(rf"^\s*{re.escape(declaration)};$", rule, re.MULTILINE) is not None


def _luminance(color: str) -> float:
    channels = tuple(int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))

    def linear(channel: float) -> float:
        if channel <= 0.04045:
            return channel / 12.92
        return math.pow((channel + 0.055) / 1.055, 2.4)

    red = linear(channels[0])
    green = linear(channels[1])
    blue = linear(channels[2])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _rgb(color: str) -> tuple[int, int, int]:
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))


def test_locked_semantic_palette_is_exact() -> None:
    assert _variables(_stylesheet()) == {
        "canvas": "#0d1117",
        "surface": "#161b22",
        "raised-surface": "#21262d",
        "inactive-selection": "#30363d",
        "text": "#f0f3f6",
        "muted-text": "#b1bac4",
        "border": "#6e7681",
        "accent": "#58a6ff",
        "focus": "#f2cc60",
        "focused-selection": "#174ea6",
        "addition-background": "#142b1d",
        "removal-background": "#351b20",
        "diff-background": "#272822",
    }


@pytest.mark.parametrize(
    ("kind", "variable"),
    [("add", "addition-background"), ("remove", "removal-background")],
)
def test_renderer_diff_backgrounds_match_tcss(kind: str, variable: str) -> None:
    row = (
        Row(None, 1, "added", "add")
        if kind == "add"
        else Row(1, None, "removed", "remove")
    )
    line = render_diff_rows(FileEntry("example.txt", Side.STAGED, "M"), [row])[0]

    expected = _rgb(_variables(_stylesheet())[variable])
    backgrounds = [
        span.style
        for span in line.spans
        if isinstance(span.style, Style)
        and span.style.bgcolor is not None
        and tuple(span.style.bgcolor.get_truecolor()) == expected
    ]
    assert len(backgrounds) == 1
    assert backgrounds[0].color is None


@pytest.mark.parametrize(
    ("selector", "declarations"),
    [
        ("Screen", ("background: $canvas", "color: $text")),
        ("#body", ("background: $canvas", "color: $text")),
        ("#sidebar", ("background: $surface",)),
        (
            ".panel-title,\n.viewer-title,\n#branch-status",
            ("background: $raised-surface", "color: $muted-text", "text-style: bold"),
        ),
        (
            "#staged-list,\n#unstaged-list,\n#commit-tree",
            ("background: $surface", "color: $text", "border: solid $border"),
        ),
        (
            "#diff-view,\n#preview-view",
            (
                "background: $diff-background",
                "color: $text",
                "scrollbar-color: $accent",
            ),
        ),
    ],
)
def test_surface_rules_use_the_locked_palette(
    selector: str, declarations: tuple[str, ...]
) -> None:
    rule = _rule(_stylesheet(), selector)
    for declaration in declarations:
        assert _has_declaration(rule, declaration)


def test_text_selection_has_readable_foreground_and_background() -> None:
    rule = _rule(_stylesheet(), "Screen > .screen--selection")

    assert _has_declaration(rule, "background: $focused-selection")
    assert _has_declaration(rule, "color: $text")


def test_list_states_have_the_locked_hierarchy() -> None:
    stylesheet = _stylesheet()
    expected = {
        "ListView > ListItem": ("background: $surface", "color: $text"),
        "ListView > ListItem.-hovered": ("background: $raised-surface",),
        "ListView > ListItem.-highlight": (
            "background: $inactive-selection",
            "color: $text",
        ),
        "ListView:focus": ("border: solid $focus",),
        "ListView:focus > ListItem.-highlight": (
            "background: $focused-selection",
            "color: $text",
            "text-style: bold",
        ),
    }

    for selector, declarations in expected.items():
        rule = _rule(stylesheet, selector)
        for declaration in declarations:
            assert _has_declaration(rule, declaration)

    item_state_rules = list(
        re.finditer(r"^([^\n{]*ListItem[^\n{]*)\s*\{", stylesheet, re.MULTILINE)
    )
    assert item_state_rules, "missing ListItem state rules"
    assert (
        item_state_rules[-1].group(1).strip() == "ListView:focus > ListItem.-highlight"
    )


def test_status_list_entries_are_single_line() -> None:
    stylesheet = _stylesheet()

    assert _has_declaration(_rule(stylesheet, "ListView > ListItem"), "height: 1")
    assert _has_declaration(
        _rule(stylesheet, "ListView > ListItem > Static"), "text-wrap: nowrap"
    )


def test_diff_title_reserves_space_for_right_aligned_navigation() -> None:
    stylesheet = _stylesheet()

    assert _has_declaration(_rule(stylesheet, ".viewer-title-label"), "width: 1fr")
    assert _has_declaration(_rule(stylesheet, ".diff-actions"), "width: auto")
    assert _has_declaration(
        _rule(stylesheet, ".file-action,\n.header-action,\n.diff-action"), "width: 3"
    )


def test_layout_and_code_view_contracts_are_retained() -> None:
    stylesheet = _stylesheet()
    sidebar = _rule(stylesheet, "#sidebar")
    lists = _rule(stylesheet, "#staged-list,\n#unstaged-list,\n#commit-tree")
    code_views = _rule(stylesheet, "#diff-view,\n#preview-view")
    wrapped_views = _rule(stylesheet, "#diff-view.wrapped,\n#preview-view.wrapped")

    assert _has_declaration(_rule(stylesheet, "#body"), "height: 1fr")
    assert _has_declaration(sidebar, "width: 30")
    assert _has_declaration(sidebar, "min-width: 15")
    assert not _has_declaration(sidebar, "max-width: 30")
    assert _has_declaration(_rule(stylesheet, ".sidebar-section"), "height: 1fr")
    assert _has_declaration(lists, "height: 1fr")
    assert _has_declaration(code_views, "overflow: scroll scroll")
    assert _has_declaration(code_views, "scrollbar-color: $accent")
    assert _has_declaration(wrapped_views, "overflow-x: hidden")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("#f0f3f6", "#0d1117"),
        ("#f0f3f6", "#161b22"),
        ("#b1bac4", "#161b22"),
        ("#f0f3f6", "#21262d"),
        ("#f0f3f6", "#30363d"),
        ("#f0f3f6", "#174ea6"),
        ("#f0f3f6", "#142b1d"),
        ("#f0f3f6", "#351b20"),
        ("#f0f3f6", "#272822"),
    ],
)
def test_locked_text_pairs_meet_contrast_floor(first: str, second: str) -> None:
    assert _contrast(first, second) >= 4.5


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("#f2cc60", "#161b22"),
        ("#58a6ff", "#0d1117"),
        ("#6e7681", "#161b22"),
    ],
)
def test_locked_indicator_pairs_meet_contrast_floor(first: str, second: str) -> None:
    assert _contrast(first, second) >= 3.0
