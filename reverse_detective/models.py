"""Shared data models for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Mapping

GameStatus = Literal["ongoing", "player_win", "player_lose", "special_ending"]
Point = tuple[int, int]
PatrolPath = tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class SceneBackdrop:
    background_image: str
    bgm: str
    description: str


@dataclass(frozen=True, slots=True)
class InteractableState:
    opened: bool = False
    locked: bool = False
    hidden: bool = False
    disabled: bool = False

    def matches(self, expected: Mapping[str, bool]) -> bool:
        for key, value in expected.items():
            if getattr(self, key) != value:
                return False
        return True

    def updated(self, changes: Mapping[str, bool]) -> "InteractableState":
        state = self
        for key, value in changes.items():
            state = replace(state, **{key: value})
        return state

    def to_dict(self) -> dict[str, bool]:
        return {
            "opened": self.opened,
            "locked": self.locked,
            "hidden": self.hidden,
            "disabled": self.disabled,
        }


@dataclass(frozen=True, slots=True)
class ActionLocalLogic:
    requires_state: dict[str, bool] = field(default_factory=dict)
    set_state: dict[str, bool] = field(default_factory=dict)
    success_text: str | None = None
    failure_text: str | None = None


@dataclass(frozen=True, slots=True)
class ActionOption:
    label: str
    action_id: str
    local_logic: ActionLocalLogic | None = None


@dataclass(frozen=True, slots=True)
class NPC:
    id: str
    name: str
    image: str
    position: Point
    patrol: PatrolPath | None


@dataclass(frozen=True, slots=True)
class Interactable:
    id: str
    name: str
    image: str
    position: Point
    options: tuple[ActionOption, ...]
    state: InteractableState = field(default_factory=InteractableState)


@dataclass(frozen=True, slots=True)
class SceneState:
    scene: SceneBackdrop
    npcs: tuple[NPC, ...]
    interactables: tuple[Interactable, ...]
    narrative: str
    game_status: GameStatus
    ending_text: str | None

    @property
    def is_terminal(self) -> bool:
        return self.game_status != "ongoing"


@dataclass(frozen=True, slots=True)
class StoryPremise:
    story_id: str
    story_title: str
    story_subtitle: str
    simulation_operator_name: str
    simulation_background: str
    simulation_briefing: str
    player_role_id: str
    player_role_name: str
    player_display_name: str
    player_identity: str
    player_strategy_kind: str
    victim_identity: str
    victim_name: str
    detective_identity: str
    detective_name: str
    setting: str
    motive: str
    initial_goal: str
    hidden_objective: str
    opening_hook: str
    primary_tool_name: str
    secondary_tool_name: str


@dataclass(frozen=True, slots=True)
class StoryTool:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class StoryRole:
    id: str
    title: str
    name: str
    background: str
    motive: str
    special_conditions: tuple[str, ...]
    signature_tools: tuple[StoryTool, ...]
    hidden_objective: str
    strategy_kind: str

    @property
    def display_name(self) -> str:
        return f"{self.title}·{self.name}"

    @property
    def primary_tool_name(self) -> str:
        return self.signature_tools[0].name

    @property
    def secondary_tool_name(self) -> str:
        if len(self.signature_tools) >= 2:
            return self.signature_tools[1].name
        return self.signature_tools[0].name


@dataclass(frozen=True, slots=True)
class StoryRule:
    title: str
    description: str
    score_delta: int


@dataclass(frozen=True, slots=True)
class StoryRanking:
    rank: str
    score_range: str
    description: str


@dataclass(frozen=True, slots=True)
class GameBackgroundDefinition:
    game_title: str
    game_subtitle: str
    operator_name: str
    background: str
    briefing: str
    menu_intro: str


@dataclass(frozen=True, slots=True)
class StoryDefinition:
    id: str
    title: str
    subtitle: str
    simulation_operator_name: str
    simulation_background: str
    simulation_briefing: str
    location: str
    setting: str
    core_case: str
    opening_hook: str
    victim_name: str
    victim_identity: str
    detective_name: str
    detective_identity: str
    roles: tuple[StoryRole, ...]
    base_score: int
    evidence_penalties: tuple[StoryRule, ...]
    task_bonuses: tuple[StoryRule, ...]
    rankings: tuple[StoryRanking, ...]


@dataclass(frozen=True, slots=True)
class ActionRecord:
    turn_index: int
    interactable_id: str
    interactable_name: str
    label: str
    action_id: str


def build_loading_scene(narrative: str = "案件生成中，请稍候。") -> SceneState:
    """Create a placeholder scene shown while the next state is loading."""

    return SceneState(
        scene=SceneBackdrop(
            background_image="placeholder_loading.png",
            bgm="silence.mp3",
            description="昏暗的宅邸在雨声里等待下一步变化。",
        ),
        npcs=(),
        interactables=(),
        narrative=narrative,
        game_status="ongoing",
        ending_text=None,
    )
