"""JSON parsing and schema validation for AI-generated scenes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any

from reverse_detective.models import (
    ActionLocalLogic,
    ActionOption,
    ActionResolutionMode,
    Interactable,
    InteractableState,
    NPC,
    Point,
    SceneBackdrop,
    SceneState,
)


class SceneValidationError(ValueError):
    """Raised when a scene payload does not match the documented schema."""


_INTERACTABLE_STATE_KEYS = {"opened", "locked", "hidden", "disabled"}
_OPTION_KEYS = {"label", "action_id", "resolution_mode", "local_logic", "sfx"}
_LOCAL_LOGIC_KEYS = {"requires_state", "set_state", "success_text", "failure_text"}
_RESOLUTION_MODES: set[ActionResolutionMode] = {"local_rule", "immediate_ai"}


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
                "state": interactable.state.to_dict(),
                "options": [
                    {
                        "label": option.label,
                        "action_id": option.action_id,
                        "resolution_mode": option.resolution_mode,
                        "sfx": option.sfx,
                        "local_logic": None
                        if option.local_logic is None
                        else {
                            "requires_state": dict(option.local_logic.requires_state),
                            "set_state": dict(option.local_logic.set_state),
                            "success_text": option.local_logic.success_text,
                            "failure_text": option.local_logic.failure_text,
                        },
                    }
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
    _require_allowed_keys(
        interactable_data,
        {"id", "name", "image", "position", "options", "state"},
        path,
    )
    _require_required_keys(interactable_data, {"id", "name", "image", "position", "options"}, path)

    options_raw = _require_sequence(interactable_data["options"], f"{path}.options")
    if not options_raw:
        raise SceneValidationError(f"{path}.options must not be empty.")

    state_raw = interactable_data.get("state")
    if state_raw is None:
        state = InteractableState()
    else:
        state = _parse_interactable_state(state_raw, f"{path}.state")

    options = tuple(_parse_option(item, index, path) for index, item in enumerate(options_raw))

    return Interactable(
        id=_require_non_empty_string(interactable_data["id"], f"{path}.id"),
        name=_require_non_empty_string(interactable_data["name"], f"{path}.name"),
        image=_require_non_empty_string(interactable_data["image"], f"{path}.image"),
        position=_require_point(interactable_data["position"], f"{path}.position"),
        options=options,
        state=state,
    )


def _parse_interactable_state(value: Any, path: str) -> InteractableState:
    state_data = _require_mapping(value, path)
    _require_exact_keys(state_data, _INTERACTABLE_STATE_KEYS, path)
    return InteractableState(
        opened=_require_bool(state_data["opened"], f"{path}.opened"),
        locked=_require_bool(state_data["locked"], f"{path}.locked"),
        hidden=_require_bool(state_data["hidden"], f"{path}.hidden"),
        disabled=_require_bool(state_data["disabled"], f"{path}.disabled"),
    )


def _parse_option(value: Any, option_index: int, parent_path: str) -> ActionOption:
    path = f"{parent_path}.options[{option_index}]"
    option_data = _require_mapping(value, path)
    _require_allowed_keys(option_data, _OPTION_KEYS, path)
    _require_required_keys(option_data, {"label", "action_id"}, path)

    resolution_mode = _require_resolution_mode(
        option_data.get("resolution_mode", "local_rule"),
        f"{path}.resolution_mode",
    )
    local_logic_raw = option_data.get("local_logic")
    local_logic = (
        None if local_logic_raw is None else _parse_local_logic(local_logic_raw, f"{path}.local_logic")
    )
    if resolution_mode == "local_rule":
        if local_logic is None:
            raise SceneValidationError(
                f"{path}.local_logic must be an object for local_rule options."
            )
        _require_local_rule_feedback(local_logic, path)

    return ActionOption(
        label=_require_non_empty_string(option_data["label"], f"{path}.label"),
        action_id=_require_non_empty_string(option_data["action_id"], f"{path}.action_id"),
        resolution_mode=resolution_mode,
        local_logic=local_logic,
        sfx=_require_optional_string(option_data.get("sfx"), f"{path}.sfx"),
    )


def _parse_local_logic(value: Any, path: str) -> ActionLocalLogic:
    logic_data = _require_mapping(value, path)
    _require_exact_keys(logic_data, _LOCAL_LOGIC_KEYS, path)
    return ActionLocalLogic(
        requires_state=_require_partial_state_map(logic_data["requires_state"], f"{path}.requires_state"),
        set_state=_require_partial_state_map(logic_data["set_state"], f"{path}.set_state"),
        success_text=_require_optional_string(logic_data["success_text"], f"{path}.success_text"),
        failure_text=_require_optional_string(logic_data["failure_text"], f"{path}.failure_text"),
    )


def _require_local_rule_feedback(logic: ActionLocalLogic, path: str) -> None:
    if logic.success_text is None:
        raise SceneValidationError(
            f"{path}.local_logic.success_text must be a non-empty string for local_rule options."
        )
    if logic.failure_text is None:
        raise SceneValidationError(
            f"{path}.local_logic.failure_text must be a non-empty string for local_rule options."
        )


def _require_partial_state_map(value: Any, path: str) -> dict[str, bool]:
    state_data = _require_mapping(value, path)
    invalid_keys = sorted(set(state_data.keys()) - _INTERACTABLE_STATE_KEYS)
    if invalid_keys:
        raise SceneValidationError(f"{path} contains invalid state keys {invalid_keys!r}.")

    parsed: dict[str, bool] = {}
    for key, raw_value in state_data.items():
        parsed[key] = _require_bool(raw_value, f"{path}.{key}")
    return parsed


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


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise SceneValidationError(f"{path} must be a boolean.")
    return value


def _require_point(value: Any, path: str) -> Point:
    if isinstance(value, Mapping):
        return _require_mapping_point(value, path)

    point_values = _require_sequence(value, path)
    if len(point_values) != 2:
        raise SceneValidationError(f"{path} must contain exactly two integers.")
    return (
        _require_integer_coordinate(point_values[0], f"{path}[0]"),
        _require_integer_coordinate(point_values[1], f"{path}[1]"),
    )


def _require_mapping_point(value: Mapping[str, Any], path: str) -> Point:
    point_data = dict(value)
    missing = [key for key in ("x", "y") if key not in point_data]
    if missing:
        raise SceneValidationError(f"{path} must contain x and y coordinates.")

    return (
        _require_integer_coordinate(point_data["x"], f"{path}.x"),
        _require_integer_coordinate(point_data["y"], f"{path}.y"),
    )


def _require_integer_coordinate(value: Any, path: str) -> int:
    if isinstance(value, bool):
        raise SceneValidationError(f"{path} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise SceneValidationError(f"{path} must be an integer.")


def _require_game_status(value: Any, path: str) -> str:
    status = _require_non_empty_string(value, path)
    valid_statuses = {"ongoing", "player_win", "player_lose", "special_ending"}
    if status not in valid_statuses:
        raise SceneValidationError(
            f"{path} must be one of {sorted(valid_statuses)!r}, got {status!r}."
        )
    return status


def _require_resolution_mode(value: Any, path: str) -> ActionResolutionMode:
    mode = _require_non_empty_string(value, path)
    if mode not in _RESOLUTION_MODES:
        raise SceneValidationError(
            f"{path} must be one of {sorted(_RESOLUTION_MODES)!r}, got {mode!r}."
        )
    return mode


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


def _require_allowed_keys(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    extra = sorted(set(value.keys()) - allowed)
    if extra:
        raise SceneValidationError(f"{path} has invalid schema: unexpected keys {extra!r}.")


def _require_required_keys(value: Mapping[str, Any], required: set[str], path: str) -> None:
    missing = sorted(required - set(value.keys()))
    if missing:
        raise SceneValidationError(f"{path} has invalid schema: missing keys {missing!r}.")
