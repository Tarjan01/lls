from __future__ import annotations

from reverse_detective.ai_client import build_default_premise
from reverse_detective.game_state import GameSessionState
from reverse_detective.scene_loader import load_scene_payload


def _build_local_logic_scene():
    return load_scene_payload(
        {
            "scene": {
                "background_image": "mansion_study_room.png",
                "bgm": "tense_loop.mp3",
                "description": "关键决策测试场景",
            },
            "npcs": [],
            "interactables": [
                {
                    "id": "study_door",
                    "name": "书房门",
                    "image": "locked_door.png",
                    "position": [640, 260],
                    "state": {
                        "opened": False,
                        "locked": True,
                        "hidden": False,
                        "disabled": False,
                    },
                    "options": [
                        {
                            "label": "撬开门锁",
                            "action_id": "unlock_door",
                            "local_logic": {
                                "requires_state": {"locked": True},
                                "set_state": {"locked": False},
                                "success_text": "门锁被你悄悄解开。",
                                "failure_text": "门锁已经开了。",
                            },
                        },
                        {
                            "label": "推开房门",
                            "action_id": "open_door",
                            "local_logic": {
                                "requires_state": {"locked": False, "opened": False},
                                "set_state": {"opened": True, "disabled": True},
                                "success_text": "你推开了房门。",
                                "failure_text": "现在还推不开。",
                            },
                        },
                    ],
                },
                {
                    "id": "clock",
                    "name": "走廊挂钟",
                    "image": "case_file.png",
                    "position": [220, 260],
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
                            "local_logic": None
                        }
                    ],
                },
                {
                    "id": "target_window",
                    "name": "视线盲区",
                    "image": "window.png",
                    "position": [920, 260],
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
                            "local_logic": None
                        }
                    ],
                },
            ],
            "narrative": "测试本地交互与关键决策推进。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )


def test_game_state_applies_local_logic_and_hides_invalid_options() -> None:
    session = GameSessionState.create(build_default_premise())
    session.finish_initial_scene(_build_local_logic_scene())

    assert len(session.text_history) == 1
    assert session.selected_text_history is not None
    assert session.selected_text_history.title.startswith("开局场景")

    session.set_active_interactable("study_door")
    choice = session.choose_option_by_index(0)
    assert choice is not None

    resolution = session.apply_choice(choice)

    assert resolution.message == "门锁被你悄悄解开。"
    assert resolution.should_settle is False
    assert session.current_scene.interactables[0].state.locked is False
    assert len(session.round_actions) == 1
    assert session.selected_text_history is not None
    assert session.selected_text_history.body == "门锁被你悄悄解开。"

    session.set_active_interactable("study_door")
    options = session.available_options_for(session.active_interactable)  # type: ignore[arg-type]
    assert [option.action_id for option in options] == ["open_door"]


def test_game_state_keeps_local_actions_pending_until_key_decision() -> None:
    session = GameSessionState.create(build_default_premise())
    session.finish_initial_scene(_build_local_logic_scene())

    for _ in range(5):
        session.set_active_interactable("clock")
        choice = session.choose_option_by_index(0)
        assert choice is not None
        resolution = session.apply_choice(choice)

    assert resolution.should_settle is False
    assert session.needs_settlement is False
    assert len(session.round_actions) == 5
    assert session.can_force_settle is False


def test_finish_settlement_moves_round_actions_into_history() -> None:
    session = GameSessionState.create(build_default_premise())
    scene = _build_local_logic_scene()
    session.finish_initial_scene(scene)

    session.set_active_interactable("clock")
    choice = session.choose_option_by_index(0)
    assert choice is not None
    session.apply_choice(choice)

    session.finish_settlement(scene)

    assert len(session.round_actions) == 0
    assert len(session.settled_action_history) == 1
    assert session.selected_text_history is not None
    assert session.selected_text_history.title.startswith("回合结算")
    assert "测试本地交互与关键决策推进。" in session.selected_text_history.body


def test_game_state_immediate_ai_option_forces_early_settlement() -> None:
    session = GameSessionState.create(build_default_premise())
    session.finish_initial_scene(_build_local_logic_scene())

    session.set_active_interactable("target_window")
    choice = session.choose_option_by_index(0)
    assert choice is not None
    assert choice.resolution_mode == "immediate_ai"

    resolution = session.apply_choice(choice)

    assert resolution.requires_immediate_ai is True
    assert resolution.should_settle is True
    assert session.round_actions[-1].resolution_mode == "immediate_ai"


def test_game_state_can_browse_text_history() -> None:
    session = GameSessionState.create(build_default_premise())
    scene = _build_local_logic_scene()
    session.finish_initial_scene(scene)
    session.record_system_text("系统提示", "正在等待后续结算。")

    assert session.selected_text_history is not None
    assert session.selected_text_history.title == "系统提示"

    session.browse_text_history(-1)
    assert session.selected_text_history is not None
    assert session.selected_text_history.title.startswith("开局场景")

    window = session.text_history_window(5)
    assert len(window) == 2
    assert window[-1][1].title == "系统提示"
