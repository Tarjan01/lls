from __future__ import annotations

from dataclasses import replace

import pygame
import pytest

from reverse_detective.app import GameApp
from reverse_detective.config import PlayerConfig, load_config
from reverse_detective.scene_loader import load_scene_payload


def test_game_app_starts_on_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    try:
        assert app._mode == "main_menu"
        assert app._session is None
        assert app._runtime_background().operator_name == app._config.player.detective_name
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
    app._ai_client.load_cached_initial_scene = lambda premise: None  # type: ignore[method-assign]
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


def test_start_selected_story_uses_cached_initial_scene(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    submitted = {"called": False}
    cached_scene = load_scene_payload(
        {
            "scene": {
                "background_image": "bg.png",
                "bgm": "bgm.mp3",
                "description": "缓存初始场景",
            },
            "npcs": [],
            "interactables": [],
            "narrative": "这是本地缓存的开场。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    def fake_submit_initial_request() -> None:
        submitted["called"] = True

    app._submit_initial_request = fake_submit_initial_request  # type: ignore[method-assign]
    app._ai_client.load_cached_initial_scene = lambda premise: cached_scene  # type: ignore[method-assign]

    try:
        app._handle_keydown(pygame.K_RETURN)
        app._handle_keydown(pygame.K_SPACE)

        assert app._mode == "game"
        assert app._premise is not None
        assert app._session is not None
        assert app._session.loading is False
        assert app._session.current_scene.scene.description == "缓存初始场景"
        assert submitted["called"] is False
        assert app._session.selected_text_history is not None
        assert "本地预生成" in app._session.selected_text_history.title
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
        app._settings_draft.detective_name = "林岚"
        app._settings_draft.avatar_gender = "female"
        app._settings_draft.fps = 75
        app._settings_draft.base_url = "https://example.com/v1"
        app._settings_draft.api_key = "test-secret-key"
        app._settings_draft.model = "gpt-test"
        app._settings_draft.timeout_seconds = 12.5
        app._settings_draft.use_mock_when_unconfigured = True
        app._settings_draft.fallback_to_mock_on_error = False

        app._save_settings()

        assert app._config.display.title == "Reverse Detective Test"
        assert app._config.player.detective_name == "林岚"
        assert app._config.player.avatar_gender == "female"
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


def test_current_story_uses_runtime_player_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    try:
        app._config = replace(
            app._config,
            player=PlayerConfig(detective_name="林岚", avatar_gender="female"),
        )

        story = app.current_story
        background = app._runtime_background()

        assert story.detective_name == "林岚"
        assert story.simulation_operator_name == "林岚"
        assert "林岚" in story.opening_hook
        assert background.operator_name == "林岚"
        assert "林岚" in background.menu_intro
    finally:
        pygame.quit()


def test_textinput_updates_editor_for_chinese_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    try:
        app._begin_input_edit(
            field_name="detective_name",
            title="侦探名字",
            value="",
            hint_text="支持中文输入。",
        )

        app._handle_textediting("林")
        assert app._input_editor is not None
        assert app._input_editor.composition == "林"

        app._handle_textinput("林岚")

        assert app._input_editor.value == "林岚"
        assert app._input_editor.composition == ""
    finally:
        pygame.quit()


def test_begin_input_edit_sets_dynamic_text_input_rect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    captured: list[pygame.Rect] = []
    original = pygame.key.set_text_input_rect

    def fake_set_text_input_rect(rect: pygame.Rect) -> None:
        captured.append(rect.copy())
        original(rect)

    monkeypatch.setattr(pygame.key, "set_text_input_rect", fake_set_text_input_rect)

    app = GameApp(load_config())
    try:
        app._begin_input_edit(
            field_name="detective_name",
            title="侦探名字",
            value="",
        )
        app._begin_input_edit(
            field_name="__freeform_action__",
            title="自由行动",
            value="",
            multiline=True,
        )

        assert captured[0] == pygame.Rect(258, 312, app._config.display.width - 516, 52)
        assert captured[1] == pygame.Rect(258, 300, app._config.display.width - 516, 92)
    finally:
        pygame.quit()
