from __future__ import annotations

import pygame
import pytest

from reverse_detective.ai_client import build_default_premise
from reverse_detective.app import GameApp
from reverse_detective.config import load_config
from reverse_detective.game_state import GameSessionState
from reverse_detective.scene_loader import load_scene_payload


def test_game_app_uses_forced_immediate_settlement_for_flagged_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    triggered: dict[str, str] = {}

    def fake_submit_settlement_request(
        *,
        request_type: str = "round_settlement",
    ) -> None:
        triggered["request_type"] = request_type

    app._submit_settlement_request = fake_submit_settlement_request  # type: ignore[method-assign]

    premise = build_default_premise()
    scene = load_scene_payload(
        {
            "scene": {
                "background_image": "bg.png",
                "bgm": "bgm.mp3",
                "description": "关键动作测试",
            },
            "npcs": [],
            "interactables": [
                {
                    "id": "target_window",
                    "name": "视线盲区",
                    "image": "window.png",
                    "position": [640, 280],
                    "state": {
                        "opened": False,
                        "locked": False,
                        "hidden": False,
                        "disabled": False,
                    },
                    "options": [
                        {
                            "label": "执行关键动作",
                            "action_id": "critical_move",
                            "resolution_mode": "immediate_ai",
                            "local_logic": None,
                        }
                    ],
                }
            ],
            "narrative": "这里应该触发即时裁决。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    app._premise = premise
    app._session = GameSessionState.create(premise)
    app._session.finish_initial_scene(scene)
    app._mode = "game"
    app._session.set_active_interactable("target_window")

    try:
        app._handle_game_keydown(pygame.K_RETURN)
        assert triggered["request_type"] == "forced_immediate_choice"
    finally:
        pygame.quit()


def test_game_app_can_browse_text_history_while_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    premise = build_default_premise()
    scene = load_scene_payload(
        {
            "scene": {
                "background_image": "bg.png",
                "bgm": "bgm.mp3",
                "description": "加载浏览测试",
            },
            "npcs": [],
            "interactables": [],
            "narrative": "这是当前场景的叙述文本。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    app._premise = premise
    app._session = GameSessionState.create(premise)
    app._session.finish_initial_scene(scene)
    app._session.record_system_text("上一条", "第一条历史文本。")
    app._session.record_system_text("下一条", "第二条历史文本。")
    app._mode = "game"
    app._session.loading = True

    try:
        assert app._session.selected_text_history is not None
        assert app._session.selected_text_history.title == "下一条"

        app._handle_game_keydown(pygame.K_LEFT)
        assert app._session.selected_text_history is not None
        assert app._session.selected_text_history.title == "上一条"

        app._handle_game_keydown(pygame.K_RIGHT)
        assert app._session.selected_text_history is not None
        assert app._session.selected_text_history.title == "下一条"
    finally:
        pygame.quit()
