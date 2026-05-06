from __future__ import annotations

import pygame
import pytest

from reverse_detective.ai_client import build_default_premise
from reverse_detective.app import GameApp
from reverse_detective.config import load_config
from reverse_detective.game_state import GameSessionState
from reverse_detective.scene_loader import load_scene_payload


def _build_two_option_scene() -> dict:
    return {
        "scene": {
            "background_image": "bg.png",
            "bgm": "bgm.mp3",
            "description": "焦点切换测试",
        },
        "npcs": [],
        "interactables": [
            {
                "id": "target_window",
                "name": "观察点",
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
                        "label": "继续观察",
                        "action_id": "wait",
                        "resolution_mode": "local_rule",
                        "local_logic": {
                            "requires_state": {},
                            "set_state": {},
                            "success_text": "你继续观察了片刻。",
                            "failure_text": "这里暂时没有更多变化。",
                        },
                    }
                ],
            }
        ],
        "narrative": "用于测试 Tab 在面板之间切换焦点。",
        "game_status": "ongoing",
        "ending_text": None,
    }


def _build_action_scene() -> dict:
    return {
        "scene": {
            "background_image": "bg.png",
            "bgm": "bgm.mp3",
            "description": "底部动作槽点击测试",
        },
        "npcs": [],
        "interactables": [
            {
                "id": "case_file",
                "name": "案卷",
                "image": "case_file.png",
                "position": [580, 280],
                "state": {
                    "opened": False,
                    "locked": False,
                    "hidden": False,
                    "disabled": False,
                },
                "options": [
                    {
                        "label": "检查案卷",
                        "action_id": "inspect_file",
                        "resolution_mode": "local_rule",
                        "local_logic": {
                            "requires_state": {"opened": False},
                            "set_state": {"opened": True},
                            "success_text": "你翻看了案卷。",
                            "failure_text": "案卷已经翻看过了。",
                        },
                    }
                ],
            }
        ],
        "narrative": "用于确认点击底部动作槽会直接执行对应选项。",
        "game_status": "ongoing",
        "ending_text": None,
    }


def test_game_app_tabs_between_panels_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    premise = build_default_premise()
    scene = load_scene_payload(_build_two_option_scene())

    app._premise = premise
    app._session = GameSessionState.create(premise)
    app._session.finish_initial_scene(scene)
    app._session.set_active_interactable("target_window")
    app._mode = "game"
    app._ensure_valid_game_panel_focus()

    try:
        app._game_renderer.draw(
            app._session,
            "Mock Story",
            0.0,
            premise.player_display_name,
            premise.story_title,
            panel_focus=app._game_panel_focus,
        )

        assert app._available_game_panels() == ("options", "sidebar")
        assert app._game_panel_focus == "options"

        app._handle_game_keydown(pygame.K_TAB)
        assert app._game_panel_focus == "sidebar"

        monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_SHIFT)
        app._handle_game_keydown(pygame.K_TAB)
        assert app._game_panel_focus == "options"
    finally:
        pygame.quit()


def test_game_app_clicks_bottom_item_slot_and_applies_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    premise = build_default_premise()
    scene = load_scene_payload(_build_action_scene())

    app._premise = premise
    app._session = GameSessionState.create(premise)
    app._session.finish_initial_scene(scene)
    app._session.set_active_interactable("case_file")
    app._mode = "game"
    app._ensure_valid_game_panel_focus()

    try:
        app._game_renderer.draw(
            app._session,
            "Mock Story",
            0.0,
            premise.player_display_name,
            premise.story_title,
            panel_focus=app._game_panel_focus,
        )

        choice_target = next(
            target for target in app._game_renderer._action_targets if target.action == "choose_option:0"
        )
        app._handle_mousebuttondown(1, choice_target.rect.center)

        assert [record.action_id for record in app._session.round_actions] == ["inspect_file"]
        assert app._session.current_scene.interactables[0].state.opened is True
    finally:
        pygame.quit()


def test_game_app_supports_keyboard_only_multi_step_flow(
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
                "description": "键盘多步流程测试",
            },
            "npcs": [],
            "interactables": [
                {
                    "id": "case_file",
                    "name": "案卷",
                    "image": "case_file.png",
                    "position": [580, 280],
                    "state": {
                        "opened": False,
                        "locked": False,
                        "hidden": False,
                        "disabled": False,
                    },
                    "options": [
                        {
                            "label": "检查案卷",
                            "action_id": "inspect_file",
                            "resolution_mode": "local_rule",
                            "local_logic": {
                                "requires_state": {"opened": False},
                                "set_state": {"opened": True},
                                "success_text": "你确认了案卷里的关键时间差。",
                                "failure_text": "案卷里没有更多新发现了。",
                            },
                        }
                    ],
                },
                {
                    "id": "disguise_kit",
                    "name": "伪装工具",
                    "image": "tool_case.png",
                    "position": [700, 280],
                    "state": {
                        "opened": False,
                        "locked": False,
                        "hidden": False,
                        "disabled": False,
                    },
                    "options": [
                        {
                            "label": "准备伪装",
                            "action_id": "prepare_disguise",
                            "resolution_mode": "local_rule",
                            "local_logic": {
                                "requires_state": {},
                                "set_state": {},
                                "success_text": "你把伪装组件提前布置好了。",
                                "failure_text": "这套伪装已经准备好了。",
                            },
                        }
                    ],
                },
            ],
            "narrative": "用于验证玩家能不靠鼠标完成多步操作。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    app._premise = premise
    app._session = GameSessionState.create(premise)
    app._session.finish_initial_scene(scene)
    app._mode = "game"
    app._session.set_active_interactable("case_file")
    app._ensure_valid_game_panel_focus()

    try:
        app._game_renderer.draw(
            app._session,
            "Mock Story",
            0.0,
            premise.player_display_name,
            premise.story_title,
            panel_focus=app._game_panel_focus,
        )

        assert app._game_panel_focus == "options"
        app._handle_game_keydown(pygame.K_RETURN)
        assert [record.action_id for record in app._session.round_actions] == ["inspect_file"]

        app._session.set_active_interactable("disguise_kit")
        app._ensure_valid_game_panel_focus()
        app._handle_game_keydown(pygame.K_RETURN)
        assert [record.action_id for record in app._session.round_actions] == [
            "inspect_file",
            "prepare_disguise",
        ]

        app._game_renderer.draw(
            app._session,
            "Mock Story",
            0.0,
            premise.player_display_name,
            premise.story_title,
            panel_focus=app._game_panel_focus,
        )

        app._handle_game_keydown(pygame.K_TAB)
        assert app._game_panel_focus == "sidebar"
        assert app._game_renderer.selected_hud_sidebar_index() == 0

        app._handle_game_keydown(pygame.K_DOWN)
        assert app._game_renderer.selected_hud_sidebar_index() == 1
    finally:
        pygame.quit()
