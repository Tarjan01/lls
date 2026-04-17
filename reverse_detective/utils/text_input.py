"""Reusable text input state for IME-friendly modal editing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TextInputSession:
    field_name: str
    title: str
    value: str
    kind: str = "text"
    multiline: bool = False
    secret: bool = False
    max_length: int = 240
    hint_text: str = ""
    placeholder: str = ""
    cursor: int = 0
    composition: str = ""

    def __post_init__(self) -> None:
        self.cursor = min(max(self.cursor, 0), len(self.value))

    @property
    def masked_value(self) -> str:
        if not self.secret:
            return self.value
        return "*" * len(self.value)

    @property
    def display_value(self) -> str:
        return self.masked_value

    def insert_text(self, text: str) -> None:
        if not text:
            return
        remaining = max(self.max_length - len(self.value), 0)
        if remaining <= 0:
            return
        inserted = text[:remaining]
        self.value = f"{self.value[:self.cursor]}{inserted}{self.value[self.cursor:]}"
        self.cursor += len(inserted)

    def backspace(self) -> None:
        if self.cursor <= 0:
            return
        self.value = f"{self.value[: self.cursor - 1]}{self.value[self.cursor:]}"
        self.cursor -= 1

    def delete_forward(self) -> None:
        if self.cursor >= len(self.value):
            return
        self.value = f"{self.value[:self.cursor]}{self.value[self.cursor + 1:]}"

    def move_left(self) -> None:
        self.cursor = max(0, self.cursor - 1)

    def move_right(self) -> None:
        self.cursor = min(len(self.value), self.cursor + 1)

    def move_home(self) -> None:
        self.cursor = 0

    def move_end(self) -> None:
        self.cursor = len(self.value)

    def set_composition(self, text: str) -> None:
        self.composition = text

    def clear_composition(self) -> None:
        self.composition = ""

