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
        assert app._mode == "main_menu"
        assert app._session is None
        assert app._background.operator_name == "江川"
        assert len(app._stories) >= 2
        assert app._main_menu_index == 0
    finally:
        pygame.quit()


def test_main_menu_can_enter_story_browser_and_start_game(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    submitted = {"called": False}

    def fake_submit_initial_request() -> None:
        submitted["called"] = True

    app._submit_initial_request = fake_submit_initial_request  # type: ignore[method-assign]
    try:
        app._handle_keydown(pygame.K_RETURN)

        assert app._mode == "story_browser"

        app._handle_keydown(pygame.K_SPACE)

        assert app._mode == "game"
        assert app._session is not None
        assert app._premise is not None
        assert submitted["called"] is True
    finally:
        pygame.quit()


def test_settings_save_updates_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    saved: dict[str, object] = {}

    def fake_save_config(config) -> None:
        saved["config"] = config

    def fake_save_api_key(path, provider, api_key) -> None:
        saved["credentials"] = (path, provider, api_key)

    monkeypatch.setattr("reverse_detective.app.save_config", fake_save_config)
    monkeypatch.setattr("reverse_detective.app.save_api_key", fake_save_api_key)

    app = GameApp(load_config())
    try:
        app._settings_draft.window_title = "Reverse Detective Test"
        app._settings_draft.fps = 75
        app._settings_draft.base_url = "https://example.com/v1"
        app._settings_draft.api_key = "test-secret-key"
        app._settings_draft.model = "gpt-test"
        app._settings_draft.timeout_seconds = 12.5
        app._settings_draft.use_mock_when_unconfigured = True
        app._settings_draft.fallback_to_mock_on_error = False

        app._save_settings()

        assert app._config.display.title == "Reverse Detective Test"
        assert app._config.display.fps == 75
        assert app._config.ai.base_url == "https://example.com/v1"
        assert app._config.ai.model == "gpt-test"
        assert app._config.ai.timeout_seconds == 12.5
        assert app._config.ai.fallback_to_mock_on_error is False
        assert saved["config"] == app._config
        assert saved["credentials"] == (
            app._config.ai.credentials_path,
            app._config.ai.provider,
            "test-secret-key",
        )
    finally:
        pygame.quit()
