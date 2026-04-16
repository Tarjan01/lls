"""Client-side local interaction helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace

from reverse_detective.models import ActionOption, Interactable, SceneState


@dataclass(frozen=True, slots=True)
class LocalActionOutcome:
    scene: SceneState
    message: str | None


def visible_interactables(scene: SceneState) -> tuple[Interactable, ...]:
    return tuple(
        interactable
        for interactable in scene.interactables
        if not interactable.state.hidden
    )


def available_options(interactable: Interactable) -> tuple[ActionOption, ...]:
    if interactable.state.hidden or interactable.state.disabled:
        return ()

    options: list[ActionOption] = []
    for option in interactable.options:
        local_logic = option.local_logic
        if local_logic is None:
            options.append(option)
            continue
        if interactable.state.matches(local_logic.requires_state):
            options.append(option)
    return tuple(options)


def scene_has_available_actions(scene: SceneState) -> bool:
    return any(available_options(interactable) for interactable in visible_interactables(scene))


def apply_local_action(
    scene: SceneState,
    interactable_id: str,
    option: ActionOption,
) -> LocalActionOutcome:
    for index, interactable in enumerate(scene.interactables):
        if interactable.id != interactable_id:
            continue
        return _apply_to_interactable(scene, index, interactable, option)

    return LocalActionOutcome(scene=scene, message=f"未能找到交互目标：{interactable_id}")


def _apply_to_interactable(
    scene: SceneState,
    index: int,
    interactable: Interactable,
    option: ActionOption,
) -> LocalActionOutcome:
    local_logic = option.local_logic
    if local_logic is None:
        return LocalActionOutcome(scene=scene, message=f"你执行了“{option.label}”。")

    if not interactable.state.matches(local_logic.requires_state):
        message = local_logic.failure_text or f"现在还不能对{interactable.name}执行“{option.label}”。"
        return LocalActionOutcome(scene=scene, message=message)

    updated_state = interactable.state.updated(local_logic.set_state)
    updated_interactable = replace(interactable, state=updated_state)
    updated_interactables = list(scene.interactables)
    updated_interactables[index] = updated_interactable
    updated_scene = replace(scene, interactables=tuple(updated_interactables))
    message = local_logic.success_text or f"你完成了“{option.label}”。"
    return LocalActionOutcome(scene=updated_scene, message=message)
