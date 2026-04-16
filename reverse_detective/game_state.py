"""Runtime game-state management for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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


TextHistoryKind = Literal["scene", "local", "system", "error"]


@dataclass(frozen=True, slots=True)
class TextHistoryEntry:
    title: str
    body: str
    kind: TextHistoryKind
    turn_index: int | None = None


@dataclass(slots=True)
class GameSessionState:
    premise: StoryPremise
    current_scene: SceneState = field(default_factory=build_loading_scene)
    settled_action_history: list[ActionRecord] = field(default_factory=list)
    round_actions: list[ActionRecord] = field(default_factory=list)
    text_history: list[TextHistoryEntry] = field(default_factory=list)
    selected_text_history_index: int = 0
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

    @property
    def selected_text_history(self) -> TextHistoryEntry | None:
        if not self.text_history:
            return None
        index = min(max(self.selected_text_history_index, 0), len(self.text_history) - 1)
        return self.text_history[index]

    def reset_for_restart(self) -> None:
        self.current_scene = build_loading_scene()
        self.settled_action_history.clear()
        self.round_actions.clear()
        self.text_history.clear()
        self.selected_text_history_index = 0
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

    def browse_text_history(self, direction: int) -> None:
        if not self.text_history:
            return
        self.selected_text_history_index = (
            self.selected_text_history_index + direction
        ) % len(self.text_history)

    def text_history_window(self, limit: int = 5) -> list[tuple[int, TextHistoryEntry]]:
        if not self.text_history or limit <= 0:
            return []

        half_window = max(0, limit // 2)
        start = max(0, self.selected_text_history_index - half_window)
        end = min(len(self.text_history), start + limit)
        start = max(0, end - limit)
        return [(index, self.text_history[index]) for index in range(start, end)]

    def record_system_text(self, title: str, body: str, *, turn_index: int | None = None) -> None:
        self._append_text_history(title, body, kind="system", turn_index=turn_index)

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
            self._append_text_history(
                f"行动 {record.turn_index} · {record.label}",
                self.local_message,
                kind="error",
                turn_index=record.turn_index,
            )
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
            self._append_text_history(
                f"行动 {record.turn_index} · {record.label}",
                self.local_message,
                kind="error",
                turn_index=record.turn_index,
            )
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
        if outcome.message:
            self._append_text_history(
                f"行动 {record.turn_index} · {record.label}",
                outcome.message,
                kind="local",
                turn_index=record.turn_index,
            )
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
        self.text_history.clear()
        self.selected_text_history_index = 0
        self._append_scene_history(
            title=f"开局场景 · {scene.scene.description}",
            scene=scene,
        )
        self.active_interactable_id = None
        self.selected_option_index = 0
        self.settled_action_history.clear()
        self.round_actions.clear()
        self.remaining_action_points = self.action_points_per_round

    def finish_settlement(self, scene: SceneState) -> None:
        round_snapshot = list(self.round_actions)
        self.settled_action_history.extend(round_snapshot)
        self.round_actions.clear()
        self.current_scene = scene
        self.loading = False
        self.error_message = None
        self.local_message = None
        if round_snapshot:
            settled_actions = " / ".join(record.label for record in round_snapshot[-3:])
            title = f"回合结算 · 第 {round_snapshot[-1].turn_index} 步"
            if settled_actions:
                title = f"{title} · {settled_actions}"
            self._append_scene_history(title=title, scene=scene, turn_index=round_snapshot[-1].turn_index)
        self.active_interactable_id = None
        self.selected_option_index = 0
        self.remaining_action_points = self.action_points_per_round

    def fail_action(self, message: str) -> None:
        self.loading = False
        self.error_message = message
        self._append_text_history("请求失败", message, kind="error")

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

    def _append_scene_history(
        self,
        *,
        title: str,
        scene: SceneState,
        turn_index: int | None = None,
    ) -> None:
        body = scene.narrative
        if scene.ending_text:
            body = f"{scene.narrative}\n\n结局：{scene.ending_text}"
        self._append_text_history(title, body, kind="scene", turn_index=turn_index)

    def _append_text_history(
        self,
        title: str,
        body: str,
        *,
        kind: TextHistoryKind,
        turn_index: int | None = None,
    ) -> None:
        cleaned_title = title.strip()
        cleaned_body = body.strip()
        if not cleaned_title or not cleaned_body:
            return

        entry = TextHistoryEntry(
            title=cleaned_title,
            body=cleaned_body,
            kind=kind,
            turn_index=turn_index,
        )
        if self.text_history and self.text_history[-1] == entry:
            self.selected_text_history_index = len(self.text_history) - 1
            return

        self.text_history.append(entry)
        self.selected_text_history_index = len(self.text_history) - 1
