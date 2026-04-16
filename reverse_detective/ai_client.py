"""AI scene generation entrypoint for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from reverse_detective.config import AIConfig
from reverse_detective.game_state import PendingChoice
from reverse_detective.models import ActionRecord, Interactable, NPC, SceneState, StoryPremise
from reverse_detective.scene_loader import load_scene_payload, scene_to_dict
from reverse_detective.story_loader import build_story_premise, load_story_catalog


PROMPT_SCHEMA = {
    "scene": {
        "background_image": "string",
        "bgm": "string",
        "description": "string",
    },
    "npcs": [
        {
            "id": "string",
            "name": "string",
            "image": "string",
            "position": [0, 0],
            "patrol": [[0, 0], [10, 10]],
        }
    ],
    "interactables": [
        {
            "id": "string",
            "name": "string",
            "image": "string",
            "position": [0, 0],
            "options": [{"label": "string", "action_id": "string"}],
        }
    ],
    "narrative": "string",
    "game_status": "ongoing",
    "ending_text": None,
}

LIVE_WORLD_WIDTH = 1280
LIVE_WORLD_HEIGHT = 520
LIVE_WORLD_X_RANGE = (96, LIVE_WORLD_WIDTH - 96)
LIVE_WORLD_Y_RANGE = (140, LIVE_WORLD_HEIGHT - 68)
LIVE_NORMALIZED_COORDINATE_MAX = 120


@dataclass(frozen=True, slots=True)
class AIRequestPayload:
    premise: StoryPremise
    current_scene: SceneState | None
    history: tuple[ActionRecord, ...]
    latest_choice: PendingChoice | None


class AIClientError(RuntimeError):
    """Raised when the configured AI provider cannot generate a valid scene."""


class ReverseDetectiveAIClient:
    """Facade for live OpenAI-compatible requests with a local mock fallback."""

    def __init__(self, config: AIConfig):
        self._config = config
        self._mock_engine = _MockStoryEngine()
        self._api_key = self._load_api_key(config.credentials_path)
        self._live_enabled = bool(config.base_url and config.model and self._api_key)
        self._last_mode_label = "Live API" if self._live_enabled else "Mock Story"

        if not self._live_enabled and not config.use_mock_when_unconfigured:
            raise AIClientError(
                "AI provider is not fully configured and mock mode has been disabled."
            )

    @property
    def mode_label(self) -> str:
        return self._last_mode_label

    def generate_initial_scene(self, premise: StoryPremise) -> SceneState:
        return self._generate_scene(
            AIRequestPayload(
                premise=premise,
                current_scene=None,
                history=(),
                latest_choice=None,
            )
        )

    def generate_next_scene(
        self,
        premise: StoryPremise,
        current_scene: SceneState,
        history: list[ActionRecord],
        latest_choice: PendingChoice,
    ) -> SceneState:
        return self._generate_scene(
            AIRequestPayload(
                premise=premise,
                current_scene=current_scene,
                history=tuple(history),
                latest_choice=latest_choice,
            )
        )

    def _generate_scene(self, request: AIRequestPayload) -> SceneState:
        if self._live_enabled:
            try:
                scene = self._generate_live_scene(request)
                self._last_mode_label = "Live API"
                return scene
            except Exception as exc:
                if not self._config.fallback_to_mock_on_error:
                    raise AIClientError(f"Live AI request failed: {exc}") from exc

        self._last_mode_label = "Mock Story"
        return self._mock_engine.generate_scene(request)

    def _generate_live_scene(self, request: AIRequestPayload) -> SceneState:
        from openai import OpenAI

        client = OpenAI(
            api_key=self._api_key,
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
        )

        with client.responses.stream(
            model=self._config.model,
            input=self._build_response_input(request),
            reasoning={"effort": self._config.reasoning_effort},
            text={"format": {"type": "json_object"}},
            store=not self._config.disable_response_storage,
            temperature=0.8,
        ) as stream:
            streamed_scene, response, streamed_text = self._consume_response_stream(stream)

        if streamed_scene is not None:
            return self._normalize_scene_layout(streamed_scene)

        raw_content = self._extract_response_content(response, streamed_text)
        try:
            return self._normalize_scene_layout(load_scene_payload(raw_content))
        except Exception as exc:
            raise AIClientError(f"Live AI returned invalid scene JSON: {exc}") from exc

    def _build_system_prompt(self) -> str:
        schema_text = json.dumps(PROMPT_SCHEMA, ensure_ascii=False, indent=2)
        return (
            "You generate scene JSON for a reverse-detective game. "
            "Return exactly one JSON object and nothing else. "
            "Do not return markdown, explanations, or code fences. "
            "After each player choice, generate the next scene from the initial premise, full action history, and latest choice. "
            "The JSON must match this schema exactly with no missing or extra fields:\n"
            f"{schema_text}\n"
            "Requirements:\n"
            "1. game_status must be one of ongoing, player_win, player_lose, special_ending.\n"
            "2. ending_text must be null when game_status is ongoing, otherwise it must contain a concrete ending text.\n"
            f"3. The playable area is {LIVE_WORLD_WIDTH}x{LIVE_WORLD_HEIGHT} pixels. Every position must use this pixel coordinate space.\n"
            f"4. Keep most x coordinates within {LIVE_WORLD_X_RANGE[0]}-{LIVE_WORLD_X_RANGE[1]} and most y coordinates within {LIVE_WORLD_Y_RANGE[0]}-{LIVE_WORLD_Y_RANGE[1]}.\n"
            "5. Every patrol must be null or an array of at least two coordinate arrays like [[x, y], [x, y]]. Never use coordinate objects.\n"
            "6. When a scene has multiple NPCs or interactables, spread them across left, center, and right areas instead of clustering them in one corner.\n"
            "7. narrative must describe the current situation and risk.\n"
            "8. All visible text content must be Simplified Chinese.\n"
        )

    def _build_user_prompt(self, request: AIRequestPayload) -> str:
        payload = {
            "request_type": "advance_scene" if request.latest_choice else "initial_scene",
            "scene_layout": {
                "coordinate_system": "pixel",
                "playable_area": {"width": LIVE_WORLD_WIDTH, "height": LIVE_WORLD_HEIGHT},
                "safe_x_range": list(LIVE_WORLD_X_RANGE),
                "safe_y_range": list(LIVE_WORLD_Y_RANGE),
                "distribution_rule": (
                    "Spread NPCs and interactables across the room. "
                    "Do not cluster every entity into the top-left corner or a tiny area."
                ),
            },
            "premise": _premise_to_dict(request.premise),
            "history": [_history_record_to_dict(item) for item in request.history],
            "latest_choice": None
            if request.latest_choice is None
            else _pending_choice_to_dict(request.latest_choice),
            "current_scene": None
            if request.current_scene is None
            else scene_to_dict(request.current_scene),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _build_response_input(self, request: AIRequestPayload) -> list[dict[str, Any]]:
        return [
            {
                "type": "message",
                "role": "developer",
                "content": self._build_system_prompt(),
            },
            {
                "type": "message",
                "role": "user",
                "content": self._build_user_prompt(request),
            },
        ]

    def _consume_response_stream(self, stream: Any) -> tuple[SceneState | None, Any, str]:
        chunks: list[str] = []
        for event in stream:
            event_type = getattr(event, "type", None)
            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", None)
                if isinstance(delta, str) and delta:
                    chunks.append(delta)
                    streamed_text = "".join(chunks)
                    streamed_scene = self._try_parse_streamed_scene(streamed_text)
                    if streamed_scene is not None:
                        return streamed_scene, None, streamed_text
                continue

            if event_type == "response.output_text.done":
                return None, None, "".join(chunks)

        return None, stream.get_final_response(), "".join(chunks)

    def _extract_response_content(self, response: Any, streamed_text: str = "") -> str:
        if streamed_text.strip():
            return streamed_text

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        output_items = getattr(response, "output", None)
        if isinstance(output_items, list):
            parts: list[str] = []
            for item in output_items:
                content = getattr(item, "content", None)
                if not isinstance(content, list):
                    continue
                for content_item in content:
                    text = getattr(content_item, "text", None)
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
                    elif isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                        parts.append(content_item["text"])
            if parts:
                return "".join(parts)

        raise AIClientError("Live AI response did not contain textual JSON output.")

    def _try_parse_streamed_scene(self, streamed_text: str) -> SceneState | None:
        candidate = streamed_text.strip()
        if not candidate:
            return None

        try:
            return load_scene_payload(candidate)
        except Exception:
            return None

    def _normalize_scene_layout(self, scene: SceneState) -> SceneState:
        points = self._scene_points(scene)
        if not points:
            return scene

        max_x = max(point[0] for point in points)
        max_y = max(point[1] for point in points)
        min_x = min(point[0] for point in points)
        min_y = min(point[1] for point in points)
        uses_small_grid = (
            min_x >= 0
            and min_y >= 0
            and max_x <= LIVE_NORMALIZED_COORDINATE_MAX
            and max_y <= LIVE_NORMALIZED_COORDINATE_MAX
        )
        if not uses_small_grid:
            return scene

        return SceneState(
            scene=scene.scene,
            npcs=tuple(self._normalize_npc(npc) for npc in scene.npcs),
            interactables=tuple(
                self._normalize_interactable(interactable)
                for interactable in scene.interactables
            ),
            narrative=scene.narrative,
            game_status=scene.game_status,
            ending_text=scene.ending_text,
        )

    def _scene_points(self, scene: SceneState) -> list[tuple[int, int]]:
        points: list[tuple[int, int]] = []
        for npc in scene.npcs:
            points.append(npc.position)
            if npc.patrol is not None:
                points.extend(npc.patrol)
        for interactable in scene.interactables:
            points.append(interactable.position)
        return points

    def _normalize_npc(self, npc: NPC) -> NPC:
        patrol = None
        if npc.patrol is not None:
            patrol = tuple(self._scale_point(point) for point in npc.patrol)

        return NPC(
            id=npc.id,
            name=npc.name,
            image=npc.image,
            position=self._scale_point(npc.position),
            patrol=patrol,
        )

    def _normalize_interactable(self, interactable: Interactable) -> Interactable:
        return Interactable(
            id=interactable.id,
            name=interactable.name,
            image=interactable.image,
            position=self._scale_point(interactable.position),
            options=interactable.options,
        )

    def _scale_point(self, point: tuple[int, int]) -> tuple[int, int]:
        x_ratio = min(max(point[0], 0), 100) / 100
        y_ratio = min(max(point[1], 0), 100) / 100
        scaled_x = LIVE_WORLD_X_RANGE[0] + x_ratio * (LIVE_WORLD_X_RANGE[1] - LIVE_WORLD_X_RANGE[0])
        scaled_y = LIVE_WORLD_Y_RANGE[0] + y_ratio * (LIVE_WORLD_Y_RANGE[1] - LIVE_WORLD_Y_RANGE[0])
        return int(round(scaled_x)), int(round(scaled_y))

    def _load_api_key(self, credentials_path: Path) -> str | None:
        if not credentials_path.exists():
            return None

        try:
            with credentials_path.open("r", encoding="utf-8") as file:
                credentials = json.load(file)
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(credentials, dict):
            return None

        candidate_keys = [
            "api_key",
            "crs_api_key",
            self._config.provider,
            f"{self._config.provider}_api_key",
        ]
        for key in candidate_keys:
            value = credentials.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return None


def build_default_premise() -> StoryPremise:
    """Return the default premise from the primary selectable story file."""

    stories = load_story_catalog()
    story = next(
        (candidate for candidate in stories if candidate.id == "tingtaoge_last_night"),
        stories[0],
    )
    return build_story_premise(story, story.roles[0].id)


class _MockStoryEngine:
    """Deterministic local story engine used when no live AI is available."""

    def generate_scene(self, request: AIRequestPayload) -> SceneState:
        history = list(request.history)
        if request.latest_choice is not None:
            history.append(request.latest_choice.to_record())

        action_ids = {record.action_id for record in history}
        latest_action = None if request.latest_choice is None else request.latest_choice.action_id

        if latest_action == "execute_clean":
            if {"inspect_clue", "prepare_tool", "prepare_support"}.issubset(action_ids):
                return load_scene_payload(
                    self._terminal_scene(
                        request.premise,
                        game_status="player_win",
                        narrative="你把关键痕迹藏进了夜色，整个行动像一场设计好的意外。",
                        ending_text="侦探最终只看到一场混乱的事故现场，没有足够证据把矛头指向你。",
                    )
                )
            return load_scene_payload(
                self._terminal_scene(
                    request.premise,
                    game_status="player_lose",
                    narrative="你仓促执行最终方案，却把自己留在了最显眼的位置。",
                    ending_text="侦探立刻锁定了你的异常举动，完美计划在最后一步失手。",
                )
            )

        if latest_action == "execute_risky":
            status = "special_ending" if "prepare_tool" in action_ids else "player_lose"
            ending_text = (
                "事情勉强被写成意外，但现场留下了几处无法彻底解释的疑点。"
                if status == "special_ending"
                else "你没有准备好足够的掩护，危险动作当场暴露。"
            )
            narrative = (
                "你提前推动了危险方案，结果介于成功与失控之间。"
                if status == "special_ending"
                else "你在关键时刻暴露了破绽。"
            )
            return load_scene_payload(
                self._terminal_scene(
                    request.premise,
                    game_status=status,
                    narrative=narrative,
                    ending_text=ending_text,
                )
            )

        narratives = {
            None: "暴雨压着整座宅邸，你只剩下一次把局势推向终局的机会。",
            "inspect_clue": "你确认了卷宗里的关键漏洞，时间窗口比想象中更窄。",
            "prepare_tool": "你已经把主要手段安置到位，只差最后的时机。",
            "prepare_support": "辅助掩护已经准备完成，现场的可控性明显提升。",
            "wait": "你暂时按兵不动，观察每个人在房间里的站位变化。",
            "ignore_clue": "你故意略过卷宗，但风险仍在悄悄累积。",
            "skip_tool": "你放弃了主手段，后续选择会变得更加危险。",
            "skip_support": "你没有准备掩护，任何激进行动都会更难收场。",
        }

        return load_scene_payload(
            self._ongoing_scene(
                request.premise,
                action_ids,
                narratives.get(latest_action, "局势正在推进，所有人都离真相更近了一步。"),
            )
        )

    def _ongoing_scene(
        self,
        premise: StoryPremise,
        action_ids: set[str],
        narrative: str,
    ) -> dict[str, Any]:
        clue_done = "inspect_clue" in action_ids
        tool_done = "prepare_tool" in action_ids
        support_done = "prepare_support" in action_ids

        interactables = []
        if not clue_done:
            interactables.append(
                self._interactable(
                    "case_clue",
                    "卷宗夹",
                    [196, 430],
                    [("检查线索", "inspect_clue"), ("暂时略过", "ignore_clue")],
                )
            )
        if not tool_done:
            interactables.append(
                self._interactable(
                    "primary_tool",
                    premise.primary_tool_name,
                    [634, 356],
                    [("布置主要手段", "prepare_tool"), ("先不处理", "skip_tool")],
                )
            )
        if not support_done:
            interactables.append(
                self._interactable(
                    "support_tool",
                    premise.secondary_tool_name,
                    [1110, 266],
                    [("准备掩护", "prepare_support"), ("维持现状", "skip_support")],
                )
            )

        final_options = [("继续观察", "wait")]
        if tool_done and support_done and clue_done:
            final_options.insert(0, ("执行完美方案", "execute_clean"))
        elif tool_done:
            final_options.insert(0, ("冒险提前动手", "execute_risky"))

        interactables.append(
            self._interactable(
                "target_window",
                "视线盲区",
                [1006, 404],
                final_options,
            )
        )

        return {
            "scene": {
                "background_image": f"{premise.story_id}.png",
                "bgm": "tense_loop.mp3",
                "description": f"{premise.story_title} · 当前行动阶段",
            },
            "npcs": [
                {
                    "id": "victim",
                    "name": premise.victim_name,
                    "image": "npc_victim.png",
                    "position": [1058, 394],
                    "patrol": None,
                },
                {
                    "id": "detective",
                    "name": premise.detective_name,
                    "image": "npc_detective.png",
                    "position": [214, 308],
                    "patrol": [[180, 296], [286, 320], [240, 358]],
                },
                {
                    "id": "witness",
                    "name": "旁观者",
                    "image": "npc_witness.png",
                    "position": [648, 214],
                    "patrol": [[612, 206], [708, 224]],
                },
            ],
            "interactables": interactables,
            "narrative": narrative,
            "game_status": "ongoing",
            "ending_text": None,
        }

    def _terminal_scene(
        self,
        premise: StoryPremise,
        game_status: str,
        narrative: str,
        ending_text: str,
    ) -> dict[str, Any]:
        return {
            "scene": {
                "background_image": f"{premise.story_id}_ending.png",
                "bgm": "ending_resolve.mp3",
                "description": f"{premise.story_title} · 结局",
            },
            "npcs": [
                {
                    "id": "victim",
                    "name": premise.victim_name,
                    "image": "npc_victim.png",
                    "position": [1058, 394],
                    "patrol": None,
                },
                {
                    "id": "detective",
                    "name": premise.detective_name,
                    "image": "npc_detective.png",
                    "position": [214, 308],
                    "patrol": None,
                },
            ],
            "interactables": [],
            "narrative": narrative,
            "game_status": game_status,
            "ending_text": ending_text,
        }

    def _interactable(
        self,
        interactable_id: str,
        name: str,
        position: list[int],
        options: list[tuple[str, str]],
    ) -> dict[str, Any]:
        return {
            "id": interactable_id,
            "name": name,
            "image": f"{interactable_id}.png",
            "position": position,
            "options": [{"label": label, "action_id": action_id} for label, action_id in options],
        }


def _history_record_to_dict(record: ActionRecord) -> dict[str, Any]:
    return {
        "turn_index": record.turn_index,
        "interactable_id": record.interactable_id,
        "interactable_name": record.interactable_name,
        "label": record.label,
        "action_id": record.action_id,
    }


def _pending_choice_to_dict(choice: PendingChoice) -> dict[str, Any]:
    return {
        "turn_index": choice.turn_index,
        "interactable_id": choice.interactable_id,
        "interactable_name": choice.interactable_name,
        "label": choice.label,
        "action_id": choice.action_id,
    }


def _premise_to_dict(premise: StoryPremise) -> dict[str, str]:
    return {
        "story_id": premise.story_id,
        "story_title": premise.story_title,
        "story_subtitle": premise.story_subtitle,
        "simulation_operator_name": premise.simulation_operator_name,
        "simulation_background": premise.simulation_background,
        "simulation_briefing": premise.simulation_briefing,
        "player_role_id": premise.player_role_id,
        "player_role_name": premise.player_role_name,
        "player_display_name": premise.player_display_name,
        "player_identity": premise.player_identity,
        "player_strategy_kind": premise.player_strategy_kind,
        "victim_identity": premise.victim_identity,
        "victim_name": premise.victim_name,
        "detective_identity": premise.detective_identity,
        "detective_name": premise.detective_name,
        "setting": premise.setting,
        "motive": premise.motive,
        "initial_goal": premise.initial_goal,
        "hidden_objective": premise.hidden_objective,
        "opening_hook": premise.opening_hook,
        "primary_tool_name": premise.primary_tool_name,
        "secondary_tool_name": premise.secondary_tool_name,
    }
