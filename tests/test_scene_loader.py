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
                    {"label": "戴上手套", "action_id": "wear_gloves"},
                    {"label": "继续观察", "action_id": "leave_gloves"},
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
