import pytest

from gitpane.icons import file_label, folder_label


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("pyproject.toml", " pyproject.toml"),
        ("MODULE.PY", " MODULE.PY"),
        ("component.TSX", " component.TSX"),
        ("archive.zip", " archive.zip"),
        ("unknown.filetype", " unknown.filetype"),
    ],
)
def test_file_label_selects_icons_by_name_then_extension(
    name: str, expected: str
) -> None:
    assert file_label(name).plain == expected


def test_file_label_colors_only_the_icon_and_preserves_literal_name() -> None:
    label = file_label("[red]example.py")

    assert label.plain == " [red]example.py"
    assert [(span.start, span.end, span.style) for span in label.spans] == [
        (0, 1, "#ffbc03")
    ]


def test_folder_label_uses_colored_open_and_closed_icons() -> None:
    closed = folder_label("[folder]", expanded=False)
    opened = folder_label("[folder]", expanded=True)

    assert closed.plain == " [folder]"
    assert opened.plain == " [folder]"
    assert [(span.start, span.end, span.style) for span in closed.spans] == [
        (0, 1, "#03a9f4")
    ]
    assert [(span.start, span.end, span.style) for span in opened.spans] == [
        (0, 1, "#03a9f4")
    ]
