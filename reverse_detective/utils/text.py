"""Text helpers used by the Pygame renderer."""

from __future__ import annotations

from typing import Any


def fit_text(text: str, font: Any, max_width: int, ellipsis: str = "…") -> tuple[str, bool]:
    """Fit text to a single line within max_width and report whether it was truncated."""

    if max_width <= 0:
        return ellipsis, bool(text)
    if font.size(text)[0] <= max_width:
        return text, False

    candidate = text
    while candidate and font.size(candidate + ellipsis)[0] > max_width:
        candidate = candidate[:-1]
    return (candidate or "") + ellipsis, True


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


def clamp_lines(lines: list[str], max_lines: int) -> list[str]:
    """Clamp wrapped lines to a fixed count and append an ellipsis when needed."""

    if max_lines <= 0:
        return []
    if len(lines) <= max_lines:
        return lines

    clamped = list(lines[:max_lines])
    clamped[-1] = clamped[-1].rstrip(" .。") + "…"
    return clamped


def preview_wrapped_text(
    text: str,
    font: Any,
    max_width: int,
    max_lines: int,
) -> tuple[list[str], bool]:
    """Wrap text, clamp to max_lines and report whether the output was truncated."""

    lines = wrap_text(text, font, max_width)
    if len(lines) <= max_lines:
        return lines, False

    preview = clamp_lines(lines, max_lines)
    preview[-1], _ = fit_text(preview[-1], font, max_width)
    return preview, True
