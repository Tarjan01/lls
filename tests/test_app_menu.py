from __future__ import annotations

import pygame
import pytest

from reverse_detective.app import GameApp
from reverse_detective.config import load_config


def test_game_app_starts_on_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    try:
        assert app._mode == "menu"
        assert app._session is None
        assert app.current_story.title == "迷雾山庄的最后一夜"
        assert app.current_role.display_name == "大管家·老陈"
    finally:
        pygame.quit()
