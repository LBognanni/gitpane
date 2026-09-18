import sys
from collections.abc import Sequence
from typing import Literal, NamedTuple

from unidiff.patch import PatchSet


class Row(NamedTuple):
    old_no: int | None
    new_no: int | None
    text: str
    kind: Literal["context", "add", "remove"]


def _without_line_ending(text: str) -> str:
    if text.endswith("\r\n"):
        return text[:-2]
    if text.endswith("\n"):
        return text[:-1]
    return text


def parse(text: str) -> list[Row]:
    rows: list[Row] = []

    for patched_file in PatchSet(text):
        for hunk in patched_file:
            for line in hunk:
                line_text = _without_line_ending(line.value)
                if line.is_context:
                    rows.append(
                        Row(
                            line.source_line_no,
                            line.target_line_no,
                            line_text,
                            "context",
                        )
                    )
                elif line.is_removed:
                    rows.append(Row(line.source_line_no, None, line_text, "remove"))
                elif line.is_added:
                    rows.append(Row(None, line.target_line_no, line_text, "add"))

    return rows


def first_change_index(rows: Sequence[Row]) -> int | None:
    changes = change_indices(rows)
    return changes[0] if changes else None


def change_indices(rows: Sequence[Row]) -> tuple[int, ...]:
    """Return the first row index of each contiguous changed block."""
    return tuple(
        index
        for index, row in enumerate(rows)
        if row.kind in ("add", "remove")
        and (index == 0 or rows[index - 1].kind == "context")
    )


def main() -> None:
    rows = parse(sys.stdin.read())
    print(f"Rows: {len(rows)}")
    print(f"First change: {first_change_index(rows)}")


if __name__ == "__main__":
    main()
