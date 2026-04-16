"""Shared data models for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GameStatus = Literal["ongoing", "player_win", "player_lose", "special_ending"]
Point = tuple[int, int]
PatrolPath = tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class SceneBackdrop:
    background_image: str
    bgm: str
    description: str


@dataclass(frozen=True, slots=True)
class ActionOption:
    label: str
    action_id: str


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
    player_identity: str
    victim_identity: str
    detective_identity: str
    setting: str
    motive: str
    initial_goal: str


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
            description="昏暗的宅邸在雨声中等待下一步变化。",
        ),
        npcs=(),
        interactables=(),
        narrative=narrative,
        game_status="ongoing",
        ending_text=None,
    )
