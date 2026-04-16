"""JSON parsing and schema validation for AI-generated scenes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any

from reverse_detective.models import (
    ActionOption,
    Interactable,
    NPC,
    Point,
    SceneBackdrop,
    SceneState,
)


class SceneValidationError(ValueError):
    """Raised when a scene payload does not match the documented schema."""


def load_scene_payload(payload: str | Mapping[str, Any]) -> SceneState:
    """Parse and validate a scene payload from a JSON string or mapping."""

    if isinstance(payload, str):
        try:
            raw_payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SceneValidationError(f"Invalid JSON payload: {exc.msg}") from exc
    else:
        raw_payload = dict(payload)

    if not isinstance(raw_payload, dict):
        raise SceneValidationError("Scene payload must be a JSON object.")

    _require_exact_keys(
        raw_payload,
        {"scene", "npcs", "interactables", "narrative", "game_status", "ending_text"},
        "root",
    )

    scene_data = _require_mapping(raw_payload["scene"], "scene")
    _require_exact_keys(scene_data, {"background_image", "bgm", "description"}, "scene")

    npcs_raw = _require_sequence(raw_payload["npcs"], "npcs")
    interactables_raw = _require_sequence(raw_payload["interactables"], "interactables")
    narrative = _require_non_empty_string(raw_payload["narrative"], "narrative")
    game_status = _require_game_status(raw_payload["game_status"], "game_status")
    ending_text = _require_optional_string(raw_payload["ending_text"], "ending_text")

    return SceneState(
        scene=SceneBackdrop(
            background_image=_require_non_empty_string(
                scene_data["background_image"], "scene.background_image"
            ),
            bgm=_require_non_empty_string(scene_data["bgm"], "scene.bgm"),
            description=_require_non_empty_string(scene_data["description"], "scene.description"),
        ),
        npcs=tuple(_parse_npc(item, index) for index, item in enumerate(npcs_raw)),
        interactables=tuple(
            _parse_interactable(item, index) for index, item in enumerate(interactables_raw)
        ),
        narrative=narrative,
        game_status=game_status,
        ending_text=ending_text,
    )


def scene_to_dict(scene: SceneState) -> dict[str, Any]:
    """Convert a validated scene back into a JSON-serializable mapping."""

    return {
        "scene": {
            "background_image": scene.scene.background_image,
            "bgm": scene.scene.bgm,
            "description": scene.scene.description,
        },
        "npcs": [
            {
                "id": npc.id,
                "name": npc.name,
                "image": npc.image,
                "position": list(npc.position),
                "patrol": None if npc.patrol is None else [list(point) for point in npc.patrol],
            }
            for npc in scene.npcs
        ],
        "interactables": [
            {
                "id": interactable.id,
                "name": interactable.name,
                "image": interactable.image,
                "position": list(interactable.position),
                "options": [
                    {"label": option.label, "action_id": option.action_id}
                    for option in interactable.options
                ],
            }
            for interactable in scene.interactables
        ],
        "narrative": scene.narrative,
        "game_status": scene.game_status,
        "ending_text": scene.ending_text,
    }


def _parse_npc(value: Any, index: int) -> NPC:
    path = f"npcs[{index}]"
    npc_data = _require_mapping(value, path)
    _require_exact_keys(npc_data, {"id", "name", "image", "position", "patrol"}, path)

    patrol_raw = npc_data["patrol"]
    patrol = None
    if patrol_raw is not None:
        patrol_points = _require_sequence(patrol_raw, f"{path}.patrol")
        if len(patrol_points) < 2:
            raise SceneValidationError(f"{path}.patrol must contain at least two points.")
        patrol = tuple(
            _require_point(point_value, f"{path}.patrol[{point_index}]")
            for point_index, point_value in enumerate(patrol_points)
        )

    return NPC(
        id=_require_non_empty_string(npc_data["id"], f"{path}.id"),
        name=_require_non_empty_string(npc_data["name"], f"{path}.name"),
        image=_require_non_empty_string(npc_data["image"], f"{path}.image"),
        position=_require_point(npc_data["position"], f"{path}.position"),
        patrol=patrol,
    )


def _parse_interactable(value: Any, index: int) -> Interactable:
    path = f"interactables[{index}]"
    interactable_data = _require_mapping(value, path)
    _require_exact_keys(
        interactable_data,
        {"id", "name", "image", "position", "options"},
        path,
    )

    options_raw = _require_sequence(interactable_data["options"], f"{path}.options")
    if not options_raw:
        raise SceneValidationError(f"{path}.options must not be empty.")

    options = tuple(_parse_option(item, index, path) for index, item in enumerate(options_raw))

    return Interactable(
        id=_require_non_empty_string(interactable_data["id"], f"{path}.id"),
        name=_require_non_empty_string(interactable_data["name"], f"{path}.name"),
        image=_require_non_empty_string(interactable_data["image"], f"{path}.image"),
        position=_require_point(interactable_data["position"], f"{path}.position"),
        options=options,
    )


def _parse_option(value: Any, option_index: int, parent_path: str) -> ActionOption:
    path = f"{parent_path}.options[{option_index}]"
    option_data = _require_mapping(value, path)
    _require_exact_keys(option_data, {"label", "action_id"}, path)

    return ActionOption(
        label=_require_non_empty_string(option_data["label"], f"{path}.label"),
        action_id=_require_non_empty_string(option_data["action_id"], f"{path}.action_id"),
    )


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SceneValidationError(f"{path} must be an object.")
    return dict(value)


def _require_sequence(value: Any, path: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SceneValidationError(f"{path} must be an array.")
    return list(value)


def _require_non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SceneValidationError(f"{path} must be a non-empty string.")
    return value.strip()


def _require_optional_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, path)


def _require_point(value: Any, path: str) -> Point:
    point_values = _require_sequence(value, path)
    if len(point_values) != 2 or not all(isinstance(item, int) for item in point_values):
        raise SceneValidationError(f"{path} must contain exactly two integers.")
    return int(point_values[0]), int(point_values[1])


def _require_game_status(value: Any, path: str) -> str:
    status = _require_non_empty_string(value, path)
    valid_statuses = {"ongoing", "player_win", "player_lose", "special_ending"}
    if status not in valid_statuses:
        raise SceneValidationError(
            f"{path} must be one of {sorted(valid_statuses)!r}, got {status!r}."
        )
    return status


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], path: str) -> None:
    actual = set(value.keys())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        fragments: list[str] = []
        if missing:
            fragments.append(f"missing keys {missing!r}")
        if extra:
            fragments.append(f"unexpected keys {extra!r}")
        raise SceneValidationError(f"{path} has invalid schema: {', '.join(fragments)}.")
