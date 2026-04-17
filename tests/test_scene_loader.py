from __future__ import annotations

import pytest

from reverse_detective.scene_loader import SceneValidationError, load_scene_payload, scene_to_dict


def test_load_scene_payload_accepts_valid_schema() -> None:
    payload = {
        "scene": {
            "background_image": "scene_villa_hall.png",
            "bgm": "rainy_night.mp3",
            "description": "暴雨敲打着别墅的落地窗。",
        },
        "npcs": [
            {
                "id": "victim_zhao",
                "name": "赵铭",
                "image": "npc_zhao.png",
                "position": [620, 260],
                "patrol": None,
            },
            {
                "id": "detective_gu",
                "name": "顾闻舟",
                "image": "npc_gu.png",
                "position": [240, 270],
                "patrol": [[240, 270], [420, 270]],
            },
        ],
        "interactables": [
            {
                "id": "gloves",
                "name": "皮手套",
                "image": "item_gloves.png",
                "position": [220, 450],
                "options": [
                    {
                        "label": "戴上手套",
                        "action_id": "wear_gloves",
                        "resolution_mode": "local_rule",
                        "local_logic": {
                            "requires_state": {"disabled": False},
                            "set_state": {"disabled": True},
                            "success_text": "你戴上手套，处理痕迹时会更从容。",
                            "failure_text": "这副手套已经被你处理过了。",
                        },
                    },
                    {
                        "label": "继续观察",
                        "action_id": "leave_gloves",
                        "resolution_mode": "local_rule",
                        "local_logic": {
                            "requires_state": {},
                            "set_state": {},
                            "success_text": "你暂时没有动这副手套，只把它的位置和可见度记在心里。",
                            "failure_text": "你再次打量这副手套，也没有得到更多变化。",
                        },
                    },
                ],
            }
        ],
        "narrative": "赵铭还没有意识到危险正在靠近。",
        "game_status": "ongoing",
        "ending_text": None,
    }

    scene = load_scene_payload(payload)

    assert scene.scene.background_image == "scene_villa_hall.png"
    assert scene.npcs[1].patrol == ((240, 270), (420, 270))
    assert scene.interactables[0].options[0].action_id == "wear_gloves"
    assert scene.interactables[0].options[0].resolution_mode == "local_rule"
    assert scene.interactables[0].options[1].resolution_mode == "local_rule"
    assert scene_to_dict(scene)["game_status"] == "ongoing"


def test_load_scene_payload_rejects_missing_required_keys() -> None:
    payload = {
        "scene": {
            "background_image": "scene_villa_hall.png",
            "bgm": "rainy_night.mp3",
        },
        "npcs": [],
        "interactables": [],
        "narrative": "还缺了描述字段。",
        "game_status": "ongoing",
        "ending_text": None,
    }

    with pytest.raises(SceneValidationError):
        load_scene_payload(payload)


def test_load_scene_payload_rejects_extra_keys() -> None:
    payload = {
        "scene": {
            "background_image": "scene_villa_hall.png",
            "bgm": "rainy_night.mp3",
            "description": "风声更急了。",
            "lighting": "low",
        },
        "npcs": [],
        "interactables": [],
        "narrative": "额外字段不应通过校验。",
        "game_status": "ongoing",
        "ending_text": None,
    }

    with pytest.raises(SceneValidationError):
        load_scene_payload(payload)


def test_load_scene_payload_accepts_object_coordinates() -> None:
    payload = {
        "scene": {
            "background_image": "bg.png",
            "bgm": "bgm.mp3",
            "description": "简述",
        },
        "npcs": [
            {
                "id": "watcher",
                "name": "守夜人",
                "image": "npc.png",
                "position": {"x": 320, "y": 180},
                "patrol": [
                    {"x": 320, "y": 180},
                    {"x": 420, "y": 180},
                ],
            }
        ],
        "interactables": [
            {
                "id": "cabinet",
                "name": "柜子",
                "image": "item.png",
                "position": {"x": 240, "y": 360},
                "options": [
                    {
                        "label": "查看",
                        "action_id": "inspect",
                        "resolution_mode": "local_rule",
                        "local_logic": {
                            "requires_state": {},
                            "set_state": {},
                            "success_text": "你查看了柜子表面，确认上面没有新的指纹遮掩。",
                            "failure_text": "你再次查看柜子，也没有更多新信息。",
                        },
                    }
                ],
            }
        ],
        "narrative": "当前局势",
        "game_status": "ongoing",
        "ending_text": None,
    }

    scene = load_scene_payload(payload)

    assert scene.npcs[0].position == (320, 180)
    assert scene.npcs[0].patrol == ((320, 180), (420, 180))
    assert scene.interactables[0].position == (240, 360)
    assert scene_to_dict(scene)["npcs"][0]["patrol"] == [[320, 180], [420, 180]]


def test_load_scene_payload_rejects_non_integral_coordinate_values() -> None:
    payload = {
        "scene": {
            "background_image": "bg.png",
            "bgm": "bgm.mp3",
            "description": "简述",
        },
        "npcs": [
            {
                "id": "watcher",
                "name": "守夜人",
                "image": "npc.png",
                "position": [320, 180],
                "patrol": [
                    {"x": 320, "y": 180.5},
                    {"x": 420, "y": 180},
                ],
            }
        ],
        "interactables": [
            {
                "id": "cabinet",
                "name": "柜子",
                "image": "item.png",
                "position": [240, 360],
                "options": [
                    {
                        "label": "查看",
                        "action_id": "inspect",
                        "resolution_mode": "local_rule",
                        "local_logic": {
                            "requires_state": {},
                            "set_state": {},
                            "success_text": "你查看了柜子表面，准备确认坐标是否合理。",
                            "failure_text": "你再次查看柜子，也没有更多可用变化。",
                        },
                    }
                ],
            }
        ],
        "narrative": "当前局势",
        "game_status": "ongoing",
        "ending_text": None,
    }

    with pytest.raises(SceneValidationError, match="must be an integer"):
        load_scene_payload(payload)


def test_load_scene_payload_parses_interactable_state_and_local_logic() -> None:
    payload = {
        "scene": {
            "background_image": "bg.png",
            "bgm": "bgm.mp3",
            "description": "本地逻辑测试",
        },
        "npcs": [],
        "interactables": [
            {
                "id": "door",
                "name": "书房门",
                "image": "locked_door.png",
                "position": [360, 220],
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
                        "resolution_mode": "immediate_ai",
                        "local_logic": {
                            "requires_state": {"locked": True},
                            "set_state": {"locked": False},
                            "success_text": "门锁弹开了。",
                            "failure_text": "已经解锁。",
                        },
                    }
                ],
            }
        ],
        "narrative": "本地逻辑应该被完整解析。",
        "game_status": "ongoing",
        "ending_text": None,
    }

    scene = load_scene_payload(payload)
    roundtrip = scene_to_dict(scene)

    assert scene.interactables[0].state.locked is True
    assert scene.interactables[0].options[0].local_logic is not None
    assert scene.interactables[0].options[0].resolution_mode == "immediate_ai"
    assert scene.interactables[0].options[0].local_logic.set_state == {"locked": False}
    assert roundtrip["interactables"][0]["state"]["locked"] is True
    assert roundtrip["interactables"][0]["options"][0]["resolution_mode"] == "immediate_ai"
    assert roundtrip["interactables"][0]["options"][0]["local_logic"]["success_text"] == "门锁弹开了。"


def test_load_scene_payload_rejects_invalid_resolution_mode() -> None:
    payload = {
        "scene": {
            "background_image": "bg.png",
            "bgm": "bgm.mp3",
            "description": "判定模式测试",
        },
        "npcs": [],
        "interactables": [
            {
                "id": "door",
                "name": "门",
                "image": "door.png",
                "position": [360, 220],
                "options": [
                    {
                        "label": "强行闯入",
                        "action_id": "rush_in",
                        "resolution_mode": "unknown_mode",
                    }
                ],
            }
        ],
        "narrative": "无效的判定模式不应通过。",
        "game_status": "ongoing",
        "ending_text": None,
    }

    with pytest.raises(SceneValidationError, match="resolution_mode must be one of"):
        load_scene_payload(payload)


def test_load_scene_payload_rejects_local_rule_without_local_logic() -> None:
    payload = {
        "scene": {
            "background_image": "bg.png",
            "bgm": "bgm.mp3",
            "description": "缺失反馈结构",
        },
        "npcs": [],
        "interactables": [
            {
                "id": "notes",
                "name": "便签",
                "image": "notes.png",
                "position": [320, 240],
                "options": [
                    {
                        "label": "查看便签",
                        "action_id": "inspect_notes",
                        "resolution_mode": "local_rule",
                    }
                ],
            }
        ],
        "narrative": "本地规则动作缺失反馈时不应通过校验。",
        "game_status": "ongoing",
        "ending_text": None,
    }

    with pytest.raises(SceneValidationError, match="must be an object for local_rule options"):
        load_scene_payload(payload)


def test_load_scene_payload_rejects_local_rule_without_feedback_text() -> None:
    payload = {
        "scene": {
            "background_image": "bg.png",
            "bgm": "bgm.mp3",
            "description": "缺失反馈文本",
        },
        "npcs": [],
        "interactables": [
            {
                "id": "notes",
                "name": "便签",
                "image": "notes.png",
                "position": [320, 240],
                "options": [
                    {
                        "label": "查看便签",
                        "action_id": "inspect_notes",
                        "resolution_mode": "local_rule",
                        "local_logic": {
                            "requires_state": {},
                            "set_state": {},
                            "success_text": "你快速扫过便签上的字迹。",
                            "failure_text": None,
                        },
                    }
                ],
            }
        ],
        "narrative": "本地规则动作必须同时提供成功和失败反馈。",
        "game_status": "ongoing",
        "ending_text": None,
    }

    with pytest.raises(SceneValidationError, match="failure_text must be a non-empty string"):
        load_scene_payload(payload)
