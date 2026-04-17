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


def test_game_app_routes_page_keys_to_selected_text_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    scrolled: list[int] = []
    app._mode = "game"
    app._game_renderer._selected_text_content = "已选中的长文本"

    def fake_scroll(delta: int) -> bool:
        scrolled.append(delta)
        return True

    app._game_renderer.scroll_selected_text = fake_scroll  # type: ignore[method-assign]

    try:
        app._handle_keydown(pygame.K_PAGEDOWN)
        app._handle_keydown(pygame.K_PAGEUP)

        assert scrolled == [6, -6]
    finally:
        pygame.quit()


def test_game_app_tabs_between_panels_and_opens_freeform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    triggered: list[str] = []
    premise = build_default_premise()
    scene = load_scene_payload(
        {
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
            "narrative": "用于测试 Tab 在三区之间切换焦点。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    def fake_begin_freeform_action_input() -> None:
        triggered.append("freeform")

    app._begin_freeform_action_input = fake_begin_freeform_action_input  # type: ignore[method-assign]
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

        assert app._game_panel_focus == "options"

        app._handle_game_keydown(pygame.K_TAB)
        assert app._game_panel_focus == "sidebar"

        app._handle_game_keydown(pygame.K_TAB)
        assert app._game_panel_focus == "freeform"

        app._handle_game_keydown(pygame.K_RETURN)
        assert triggered == ["freeform"]
    finally:
        pygame.quit()


def test_game_app_clicks_hud_sidebar_and_switches_focus(
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
                "description": "侧边栏点击测试",
            },
            "npcs": [],
            "interactables": [],
            "narrative": "点击右下侧边栏后应选中文本并切换焦点。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    app._premise = premise
    app._session = GameSessionState.create(premise)
    app._session.finish_initial_scene(scene)
    app._mode = "game"

    try:
        app._game_renderer.draw(
            app._session,
            "Mock Story",
            0.0,
            premise.player_display_name,
            premise.story_title,
            panel_focus=app._game_panel_focus,
        )

        sidebar_rect = app._game_renderer._hud_sidebar_targets[0].rect
        app._handle_mousebuttondown(1, sidebar_rect.center)

        assert app._game_panel_focus == "sidebar"
        assert app._game_renderer.has_selected_text() is True
    finally:
        pygame.quit()


def test_game_app_draws_visible_freeform_input_modal(
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
                "description": "自由行动输入弹窗测试",
            },
            "npcs": [],
            "interactables": [],
            "narrative": "用于确认游戏态会实际渲染自由行动输入弹窗。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    app._premise = premise
    app._session = GameSessionState.create(premise)
    app._session.finish_initial_scene(scene)
    app._mode = "game"
    app._game_panel_focus = "freeform"

    try:
        app._game_renderer.draw(
            app._session,
            "Mock Story",
            0.0,
            premise.player_display_name,
            premise.story_title,
            panel_focus=app._game_panel_focus,
        )
        before = pygame.image.tobytes(app._screen, "RGBA")

        app._handle_game_keydown(pygame.K_RETURN)
        assert app._input_editor is not None

        app._draw()
        after = pygame.image.tobytes(app._screen, "RGBA")

        assert after != before
    finally:
        pygame.quit()


def test_game_app_submits_freeform_action_for_immediate_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    triggered: dict[str, str] = {}
    premise = build_default_premise()
    scene = load_scene_payload(
        {
            "scene": {
                "background_image": "bg.png",
                "bgm": "bgm.mp3",
                "description": "自由行动测试",
            },
            "npcs": [],
            "interactables": [],
            "narrative": "玩家准备提交一条额外行动。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    def fake_submit_settlement_request(
        *,
        request_type: str = "round_settlement",
    ) -> None:
        triggered["request_type"] = request_type

    app._submit_settlement_request = fake_submit_settlement_request  # type: ignore[method-assign]
    app._premise = premise
    app._session = GameSessionState.create(premise)
    app._session.finish_initial_scene(scene)
    app._mode = "game"

    try:
        app._submit_freeform_action("伪装成馆员去套话")

        assert triggered["request_type"] == "freeform_action"
        assert app._session.round_actions[-1].action_id == "player_freeform_action"
        assert app._session.round_actions[-1].freeform_text == "伪装成馆员去套话"
    finally:
        pygame.quit()


def test_game_app_supports_keyboard_only_multi_step_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    app = GameApp(load_config())
    triggered: dict[str, str] = {}
    premise = build_default_premise()
    scene = load_scene_payload(
        {
            "scene": {
                "background_image": "bg.png",
                "bgm": "bgm.mp3",
                "description": "纯键盘多步流程测试",
            },
            "npcs": [],
            "interactables": [
                {
                    "id": "case_file",
                    "name": "案卷夹",
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
                            "label": "检查档案",
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
                                "success_text": "你把伪装组件提前布置到了顺手的位置。",
                                "failure_text": "这套伪装已经准备好了。",
                            },
                        }
                    ],
                },
            ],
            "narrative": "用于验证玩家能否不借助鼠标完成多步操作。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    def fake_submit_settlement_request(
        *,
        request_type: str = "round_settlement",
    ) -> None:
        triggered["request_type"] = request_type

    app._submit_settlement_request = fake_submit_settlement_request  # type: ignore[method-assign]
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

        app._session.set_active_interactable("disguise_kit")
        app._ensure_valid_game_panel_focus()

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

        app._handle_game_keydown(pygame.K_TAB)
        assert app._game_panel_focus == "freeform"

        app._handle_game_keydown(pygame.K_RETURN)
        assert app._input_editor is not None
        assert app._input_editor.field_name == "__freeform_action__"

        app._handle_textinput("伪装成馆员去套话")
        monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_CTRL)
        app._handle_keydown(pygame.K_RETURN)

        assert app._input_editor is None
        assert triggered["request_type"] == "freeform_action"
        assert [record.action_id for record in app._session.round_actions] == [
            "inspect_file",
            "prepare_disguise",
            "player_freeform_action",
        ]
        assert app._session.round_actions[-1].freeform_text == "伪装成馆员去套话"
    finally:
        pygame.quit()
