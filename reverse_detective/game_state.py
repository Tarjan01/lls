"""Runtime game-state management for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass, field

from reverse_detective.local_logic import (
    apply_local_action,
    available_options,
    scene_has_available_actions,
)
from reverse_detective.models import (
    ActionOption,
    ActionRecord,
    ActionResolutionMode,
    Interactable,
    SceneState,
    StoryPremise,
    build_loading_scene,
)


@dataclass(frozen=True, slots=True)
class PendingChoice:
    turn_index: int
    interactable_id: str
    interactable_name: str
    label: str
    action_id: str
    resolution_mode: ActionResolutionMode = "local_rule"

    def to_record(self) -> ActionRecord:
        return ActionRecord(
            turn_index=self.turn_index,
            interactable_id=self.interactable_id,
            interactable_name=self.interactable_name,
            label=self.label,
            action_id=self.action_id,
            resolution_mode=self.resolution_mode,
        )


@dataclass(frozen=True, slots=True)
class ChoiceResolution:
    record: ActionRecord
    message: str | None
    should_settle: bool
    requires_immediate_ai: bool = False


@dataclass(slots=True)
class GameSessionState:
    premise: StoryPremise
    current_scene: SceneState = field(default_factory=build_loading_scene)
    settled_action_history: list[ActionRecord] = field(default_factory=list)
    round_actions: list[ActionRecord] = field(default_factory=list)
    player_position: tuple[float, float] = (140.0, 500.0)
    active_interactable_id: str | None = None
    selected_option_index: int = 0
    loading: bool = True
    error_message: str | None = None
    local_message: str | None = None
    action_points_per_round: int = 5
    remaining_action_points: int = 5

    @classmethod
    def create(cls, premise: StoryPremise) -> "GameSessionState":
        return cls(premise=premise)

    @property
    def action_history(self) -> list[ActionRecord]:
        return [*self.settled_action_history, *self.round_actions]

    @property
    def total_action_count(self) -> int:
        return len(self.settled_action_history) + len(self.round_actions)

    @property
    def needs_settlement(self) -> bool:
        return bool(self.round_actions) and (
            self.remaining_action_points <= 0 or not self.has_available_actions
        )

    @property
    def has_available_actions(self) -> bool:
        return scene_has_available_actions(self.current_scene)

    @property
    def can_force_settle(self) -> bool:
        return bool(self.round_actions) and not self.loading

    def reset_for_restart(self) -> None:
        self.current_scene = build_loading_scene()
        self.settled_action_history.clear()
        self.round_actions.clear()
        self.player_position = (140.0, 500.0)
        self.active_interactable_id = None
        self.selected_option_index = 0
        self.loading = True
        self.error_message = None
        self.local_message = None
        self.remaining_action_points = self.action_points_per_round

    def set_player_position(self, x: float, y: float) -> None:
        self.player_position = (x, y)

    def set_active_interactable(self, interactable_id: str | None) -> None:
        if interactable_id is not None:
            interactable = self._find_interactable(interactable_id)
            if interactable is None or not self.available_options_for(interactable):
                interactable_id = None

        if self.active_interactable_id != interactable_id:
            self.active_interactable_id = interactable_id
            self.selected_option_index = 0
        elif interactable_id is None:
            self.selected_option_index = 0

    def cycle_options(self, direction: int) -> None:
        interactable = self.active_interactable
        if interactable is None:
            return

        options = self.available_options_for(interactable)
        option_count = len(options)
        if option_count == 0:
            self.selected_option_index = 0
            return

        self.selected_option_index = (self.selected_option_index + direction) % option_count

    def choose_option_by_index(self, index: int) -> PendingChoice | None:
        interactable = self.active_interactable
        if interactable is None:
            return None

        options = self.available_options_for(interactable)
        if index < 0 or index >= len(options):
            return None
        self.selected_option_index = index
        return self.build_pending_choice(interactable, options[index])

    def build_pending_choice(
        self,
        interactable: Interactable,
        option: ActionOption,
    ) -> PendingChoice:
        return PendingChoice(
            turn_index=self.total_action_count + 1,
            interactable_id=interactable.id,
            interactable_name=interactable.name,
            label=option.label,
            action_id=option.action_id,
            resolution_mode=option.resolution_mode,
        )

    def available_options_for(self, interactable: Interactable) -> tuple[ActionOption, ...]:
        return available_options(interactable)

    def begin_initial_load(self) -> None:
        self.loading = True
        self.error_message = None
        self.local_message = None

    def begin_action(self, choice: PendingChoice | None = None) -> None:
        self.begin_initial_load()

    def begin_settlement(self) -> None:
        self.loading = True
        self.error_message = None

    def apply_choice(self, choice: PendingChoice) -> ChoiceResolution:
        interactable = self._find_interactable(choice.interactable_id)
        if interactable is None:
            record = choice.to_record()
            self.round_actions.append(record)
            self.remaining_action_points = max(0, self.remaining_action_points - 1)
            self.local_message = f"未能找到交互目标：{choice.interactable_name}"
            self.selected_option_index = 0
            self.active_interactable_id = None
            return ChoiceResolution(
                record=record,
                message=self.local_message,
                should_settle=self.needs_settlement,
            )

        option = next(
            (
                candidate
                for candidate in self.available_options_for(interactable)
                if candidate.action_id == choice.action_id and candidate.label == choice.label
            ),
            None,
        )
        if option is None:
            record = choice.to_record()
            self.round_actions.append(record)
            self.remaining_action_points = max(0, self.remaining_action_points - 1)
            self.local_message = f"当前无法执行“{choice.label}”。"
            self.selected_option_index = 0
            self.active_interactable_id = None
            return ChoiceResolution(
                record=record,
                message=self.local_message,
                should_settle=self.needs_settlement,
            )

        outcome = apply_local_action(self.current_scene, interactable.id, option)
        self.current_scene = outcome.scene
        record = choice.to_record()
        self.round_actions.append(record)
        self.remaining_action_points = max(0, self.remaining_action_points - 1)
        self.local_message = outcome.message
        self.error_message = None
        self.active_interactable_id = None
        self.selected_option_index = 0
        requires_immediate_ai = option.resolution_mode == "immediate_ai"
        return ChoiceResolution(
            record=record,
            message=outcome.message,
            should_settle=requires_immediate_ai or self.needs_settlement,
            requires_immediate_ai=requires_immediate_ai,
        )

    def finish_initial_scene(self, scene: SceneState) -> None:
        self.current_scene = scene
        self.loading = False
        self.error_message = None
        self.local_message = None
        self.active_interactable_id = None
        self.selected_option_index = 0
        self.settled_action_history.clear()
        self.round_actions.clear()
        self.remaining_action_points = self.action_points_per_round

    def finish_settlement(self, scene: SceneState) -> None:
        self.settled_action_history.extend(self.round_actions)
        self.round_actions.clear()
        self.current_scene = scene
        self.loading = False
        self.error_message = None
        self.local_message = None
        self.active_interactable_id = None
        self.selected_option_index = 0
        self.remaining_action_points = self.action_points_per_round

    def fail_action(self, message: str) -> None:
        self.loading = False
        self.error_message = message

    @property
    def active_interactable(self) -> Interactable | None:
        if self.active_interactable_id is None:
            return None

        interactable = self._find_interactable(self.active_interactable_id)
        if interactable is None or not self.available_options_for(interactable):
            return None
        return interactable

    def _find_interactable(self, interactable_id: str) -> Interactable | None:
        for interactable in self.current_scene.interactables:
            if interactable.id == interactable_id:
                return interactable
        return None
