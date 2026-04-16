"""Runtime game-state management for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass, field

from reverse_detective.models import (
    ActionOption,
    ActionRecord,
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

    def to_record(self) -> ActionRecord:
        return ActionRecord(
            turn_index=self.turn_index,
            interactable_id=self.interactable_id,
            interactable_name=self.interactable_name,
            label=self.label,
            action_id=self.action_id,
        )


@dataclass(slots=True)
class GameSessionState:
    premise: StoryPremise
    current_scene: SceneState = field(default_factory=build_loading_scene)
    action_history: list[ActionRecord] = field(default_factory=list)
    player_position: tuple[float, float] = (140.0, 500.0)
    active_interactable_id: str | None = None
    selected_option_index: int = 0
    loading: bool = True
    error_message: str | None = None
    pending_choice: PendingChoice | None = None

    @classmethod
    def create(cls, premise: StoryPremise) -> "GameSessionState":
        return cls(premise=premise)

    def reset_for_restart(self) -> None:
        self.current_scene = build_loading_scene()
        self.action_history.clear()
        self.player_position = (140.0, 500.0)
        self.active_interactable_id = None
        self.selected_option_index = 0
        self.loading = True
        self.error_message = None
        self.pending_choice = None

    def set_player_position(self, x: float, y: float) -> None:
        self.player_position = (x, y)

    def set_active_interactable(self, interactable_id: str | None) -> None:
        if self.active_interactable_id != interactable_id:
            self.active_interactable_id = interactable_id
            self.selected_option_index = 0
        elif interactable_id is None:
            self.selected_option_index = 0

    def cycle_options(self, direction: int) -> None:
        interactable = self.active_interactable
        if interactable is None:
            return

        option_count = len(interactable.options)
        if option_count == 0:
            self.selected_option_index = 0
            return

        self.selected_option_index = (self.selected_option_index + direction) % option_count

    def choose_option_by_index(self, index: int) -> PendingChoice | None:
        interactable = self.active_interactable
        if interactable is None:
            return None
        if index < 0 or index >= len(interactable.options):
            return None
        self.selected_option_index = index
        return self.build_pending_choice(interactable, interactable.options[index])

    def build_pending_choice(
        self, interactable: Interactable, option: ActionOption
    ) -> PendingChoice:
        return PendingChoice(
            turn_index=len(self.action_history) + 1,
            interactable_id=interactable.id,
            interactable_name=interactable.name,
            label=option.label,
            action_id=option.action_id,
        )

    def begin_action(self, choice: PendingChoice | None = None) -> None:
        self.loading = True
        self.error_message = None
        self.pending_choice = choice

    def finish_initial_scene(self, scene: SceneState) -> None:
        self.current_scene = scene
        self.loading = False
        self.error_message = None
        self.pending_choice = None
        self.active_interactable_id = None
        self.selected_option_index = 0

    def finish_action(self, scene: SceneState) -> None:
        if self.pending_choice is not None:
            self.action_history.append(self.pending_choice.to_record())
        self.current_scene = scene
        self.loading = False
        self.error_message = None
        self.pending_choice = None
        self.active_interactable_id = None
        self.selected_option_index = 0

    def fail_action(self, message: str) -> None:
        self.loading = False
        self.error_message = message
        self.pending_choice = None

    @property
    def active_interactable(self) -> Interactable | None:
        if self.active_interactable_id is None:
            return None

        for interactable in self.current_scene.interactables:
            if interactable.id == self.active_interactable_id:
                return interactable

        return None
