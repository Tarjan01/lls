"""Text helpers used by the Pygame renderer."""

from __future__ import annotations

from typing import Any


def wrap_text(text: str, font: Any, max_width: int) -> list[str]:
    """Wrap Chinese or mixed text by measured width."""

    lines: list[str] = []
    current = ""

    for character in text:
        if character == "\n":
            lines.append(current.rstrip() or " ")
            current = ""
            continue

        trial = current + character
        if current and font.size(trial)[0] > max_width:
            lines.append(current.rstrip())
            current = character
        else:
            current = trial

    if current:
        lines.append(current.rstrip())

    return lines or [" "]
