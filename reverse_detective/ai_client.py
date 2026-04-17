"""AI scene generation entrypoint for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from queue import Empty, Queue
import threading
import time
from typing import Any, Literal

import httpx

from reverse_detective.config import AIConfig
from reverse_detective.game_state import PendingChoice
from reverse_detective.models import ActionRecord, SceneState, StoryPremise
from reverse_detective.scene_loader import load_scene_payload, scene_to_dict
from reverse_detective.story_loader import build_story_premise, load_story_catalog


PROMPT_SCHEMA = {
    "scene": {
        "background_image": "mansion_study_room.png",
        "bgm": "tense_loop.mp3",
        "description": "string",
    },
    "npcs": [
        {
            "id": "string",
            "name": "string",
            "image": "security_guard.png",
            "position": [0, 0],
            "patrol": [[0, 0], [10, 10]],
        }
    ],
    "interactables": [
        {
            "id": "study_door",
            "name": "书房门",
            "image": "locked_door.png",
            "position": [860, 280],
            "state": {
                "opened": False,
                "locked": True,
                "hidden": False,
                "disabled": False,
            },
            "options": [
                {
                    "label": "撬开门锁",
                    "action_id": "unlock_door",
                    "resolution_mode": "local_rule",
                    "local_logic": {
                        "requires_state": {"locked": True},
                        "set_state": {"locked": False},
                        "success_text": "你撬开了门锁。",
                        "failure_text": "这扇门现在不需要再撬。"
                    },
                }
            ],
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
ACTION_POINTS_PER_SETTLEMENT = 5
LIVE_RETRYABLE_REASONS = ("xhigh", "high", "medium", "low")
INITIAL_SCENE_CACHE_VERSION = 1
DEFAULT_INITIAL_SCENE_CACHE_ROOT = Path("~/.reverse_detective/cache/initial_scenes").expanduser()


@dataclass(frozen=True, slots=True)
class AIRequestPayload:
    request_type: Literal["initial_scene", "round_settlement", "forced_immediate_choice"]
    premise: StoryPremise
    current_scene: SceneState | None
    history: tuple[ActionRecord, ...]
    recent_actions: tuple[ActionRecord, ...]


class AIClientError(RuntimeError):
    """Raised when the configured AI provider cannot generate a valid scene."""


class ReverseDetectiveAIClient:
    """Facade for live OpenAI-compatible requests with a local mock fallback."""

    def __init__(
        self,
        config: AIConfig,
        asset_root: Path | None = None,
        cache_root: Path | None = None,
    ):
        self._config = config
        self._mock_engine = _MockStoryEngine()
        self._api_key = self._load_api_key(config.credentials_path)
        self._live_enabled = bool(config.base_url and config.model and self._api_key)
        self._last_mode_label = "Live API" if self._live_enabled else "Mock Story"
        self._initial_scene_cache_root = (cache_root or DEFAULT_INITIAL_SCENE_CACHE_ROOT).expanduser()
        self._prefetch_lock = threading.Lock()
        self._prefetch_inflight: set[str] = set()

        if not self._live_enabled and not config.use_mock_when_unconfigured:
            raise AIClientError(
                "AI provider is not fully configured and mock mode has been disabled."
            )

    @property
    def mode_label(self) -> str:
        return self._last_mode_label

    def close(self) -> None:
        return None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def generate_initial_scene(self, premise: StoryPremise) -> SceneState:
        scene = self._generate_scene(
            AIRequestPayload(
                request_type="initial_scene",
                premise=premise,
                current_scene=None,
                history=(),
                recent_actions=(),
            )
        )
        self._write_initial_scene_cache(premise, scene)
        return scene

    def load_cached_initial_scene(self, premise: StoryPremise) -> SceneState | None:
        cache_path = self._initial_scene_cache_path(premise)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(payload, dict):
            return None

        scene_payload = payload.get("scene")
        if not isinstance(scene_payload, dict):
            return None

        try:
            scene = load_scene_payload(scene_payload)
        except Exception:
            return None

        source_label = payload.get("source_mode")
        if isinstance(source_label, str) and source_label.strip():
            self._last_mode_label = source_label.strip()
        else:
            self._last_mode_label = "Cached Live API" if self._live_enabled else "Cached Mock Story"
        return scene

    def prefetch_initial_scene(self, premise: StoryPremise, *, force: bool = False) -> bool:
        cache_key = self._initial_scene_cache_key(premise)
        cache_path = self._initial_scene_cache_path(premise)
        with self._prefetch_lock:
            if cache_key in self._prefetch_inflight:
                return False
            if cache_path.exists() and not force:
                return False
            self._prefetch_inflight.add(cache_key)

        def worker() -> None:
            try:
                if force or not cache_path.exists():
                    self.generate_initial_scene(premise)
            except Exception:
                return
            finally:
                with self._prefetch_lock:
                    self._prefetch_inflight.discard(cache_key)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def settle_round(
        self,
        premise: StoryPremise,
        current_scene: SceneState,
        history: list[ActionRecord],
        recent_actions: list[ActionRecord],
        *,
        request_type: Literal["round_settlement", "forced_immediate_choice"] = "round_settlement",
    ) -> SceneState:
        return self._generate_scene(
            AIRequestPayload(
                request_type=request_type,
                premise=premise,
                current_scene=current_scene,
                history=tuple(history),
                recent_actions=tuple(recent_actions),
            )
        )

    def generate_next_scene(
        self,
        premise: StoryPremise,
        current_scene: SceneState,
        history: list[ActionRecord],
        latest_choice: PendingChoice,
    ) -> SceneState:
        return self.settle_round(
            premise,
            current_scene,
            history,
            [latest_choice.to_record()],
            request_type=(
                "forced_immediate_choice"
                if latest_choice.resolution_mode == "immediate_ai"
                else "round_settlement"
            ),
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
        last_transport_exc: Exception | None = None
        for attempt_index, (reasoning_effort, timeout_seconds) in enumerate(
            self._live_attempt_plan(),
            start=1,
        ):
            try:
                return self._stream_live_scene_with_deadline(
                    request,
                    reasoning_effort=reasoning_effort,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                if not self._is_retryable_live_error(exc):
                    raise
                last_transport_exc = exc
                if attempt_index >= len(self._live_attempt_plan()):
                    break
                time.sleep(min(0.6 * attempt_index, 1.2))

        assert last_transport_exc is not None
        raise AIClientError(self._format_live_transport_error(last_transport_exc))

    def _stream_live_scene(
        self,
        request: AIRequestPayload,
        *,
        reasoning_effort: str,
        timeout_seconds: float,
    ) -> SceneState:
        from openai import OpenAI

        client = OpenAI(
            api_key=self._api_key,
            base_url=self._config.base_url,
            timeout=self._build_live_timeout(timeout_seconds),
            max_retries=0,
        )

        with client.responses.stream(
            model=self._config.model,
            input=self._build_response_input(request),
            reasoning={"effort": reasoning_effort},
            text={"format": {"type": "json_object"}},
            store=not self._config.disable_response_storage,
            temperature=0.5,
        ) as stream:
            streamed_scene, response, streamed_text = self._consume_response_stream(stream)

        if streamed_scene is not None:
            return self._normalize_scene_layout(streamed_scene)

        raw_content = self._extract_response_content(response, streamed_text)
        try:
            return self._normalize_scene_layout(load_scene_payload(raw_content))
        except Exception as exc:
            raise AIClientError(f"Live AI returned invalid scene JSON: {exc}") from exc

    def _stream_live_scene_with_deadline(
        self,
        request: AIRequestPayload,
        *,
        reasoning_effort: str,
        timeout_seconds: float,
    ) -> SceneState:
        result_queue: Queue[tuple[str, SceneState | Exception]] = Queue(maxsize=1)

        def worker() -> None:
            try:
                scene = self._stream_live_scene(
                    request,
                    reasoning_effort=reasoning_effort,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                result_queue.put(("error", exc))
                return
            result_queue.put(("scene", scene))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        deadline_seconds = max(timeout_seconds + 0.5, 0.5)

        try:
            result_kind, payload = result_queue.get(timeout=deadline_seconds)
        except Empty as exc:
            raise TimeoutError(
                f"Live AI stream exceeded the overall deadline ({deadline_seconds:.0f}s)"
            ) from exc

        if result_kind == "error":
            assert isinstance(payload, Exception)
            raise payload

        assert isinstance(payload, SceneState)
        return payload

    def _live_attempt_plan(self) -> list[tuple[str, float]]:
        configured = (self._config.reasoning_effort or "high").strip().lower()
        attempts: list[tuple[str, float]] = [(configured, self._config.timeout_seconds)]

        fallback_reason = self._fallback_reasoning_effort(configured)
        if fallback_reason != configured:
            attempts.append((fallback_reason, self._config.timeout_seconds))

        return attempts

    def _fallback_reasoning_effort(self, configured: str) -> str:
        if configured not in LIVE_RETRYABLE_REASONS:
            return configured

        order = list(LIVE_RETRYABLE_REASONS)
        index = order.index(configured)
        if index >= len(order) - 1:
            return configured
        if configured == "xhigh":
            return "medium"
        if configured == "high":
            return "medium"
        if configured == "medium":
            return "low"
        return configured

    def _build_live_timeout(self, timeout_seconds: float) -> httpx.Timeout:
        safe_total = max(10.0, timeout_seconds)
        return httpx.Timeout(
            connect=min(10.0, max(4.0, safe_total / 3)),
            read=safe_total,
            write=min(20.0, max(6.0, safe_total / 2)),
            pool=10.0,
        )

    def _is_retryable_live_error(self, exc: Exception) -> bool:
        if isinstance(exc, AIClientError):
            return False
        try:
            from openai import APIConnectionError, APITimeoutError

            openai_retryable_types = (APIConnectionError, APITimeoutError)
        except Exception:
            openai_retryable_types = ()
        retryable_types = (
            *openai_retryable_types,
            TimeoutError,
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
            OSError,
        )
        return isinstance(exc, retryable_types)

    def _format_live_transport_error(self, exc: Exception) -> str:
        error_type = type(exc).__name__
        details = str(exc).strip() or repr(exc)
        configured = (self._config.reasoning_effort or "high").strip().lower()
        fallback_reason = self._fallback_reasoning_effort(configured)
        if fallback_reason != configured:
            retry_hint = f"已自动尝试将推理强度从 {configured} 降到 {fallback_reason} 后重试一次。"
        else:
            retry_hint = "当前推理强度没有可进一步降低的自动重试档位。"
        return (
            f"{error_type}: {details}. "
            f"请求地址 {self._config.base_url} 的网络连通或流式返回存在问题，"
            f"timeout_seconds={self._config.timeout_seconds}，且客户端已启用总时限保护。{retry_hint}"
        )

    def _build_system_prompt(self) -> str:
        schema_text = json.dumps(PROMPT_SCHEMA, ensure_ascii=False, separators=(",", ":"))
        return (
            "You generate scene JSON for a reverse-detective game. "
            "Return exactly one JSON object and nothing else. "
            "Do not return markdown, explanations, or code fences. "
            "The client performs predictable local interactions first and only asks you to settle the round after several actions, "
            "or immediately after a rare high-risk choice marked as immediate_ai. "
            "You must return the next settled scene after adjudicating the whole pending action batch. "
            "The JSON must match this schema exactly with no missing or extra root fields:\n"
            f"{schema_text}\n"
            "Requirements:\n"
            "1. game_status must be one of ongoing, player_win, player_lose, special_ending.\n"
            "2. ending_text must be null when game_status is ongoing, otherwise it must contain a concrete ending text.\n"
            "3. Every interactable must include state with opened, locked, hidden, disabled booleans.\n"
            "4. Every option must include resolution_mode and local_logic. resolution_mode must be local_rule or immediate_ai.\n"
            "5. Prefer local_rule by default. Only mark an option as immediate_ai when it can sharply change risk, social reaction, exposure, evidence, or branch outcome.\n"
            "6. Keep immediate_ai options rare: most ongoing scenes should have zero to two immediate_ai options total, and the majority of options should remain local_rule.\n"
            "7. Good local_rule examples: unlocking, opening, searching, observing, picking up known tools, simple setup, repeatable checks.\n"
            "8. Good immediate_ai examples: executing the crime, bluffing an NPC, moving a body, destroying evidence under pressure, triggering alarms, forcing confrontation, or any action whose outcome depends on dynamic reactions.\n"
            "9. local_logic can only describe same-object logic through requires_state and set_state, using only opened, locked, hidden, disabled.\n"
            "10. For local_rule options, provide local_logic whenever the result is deterministic on the current object. Use null only when the action is a simple no-op or observation.\n"
            "11. immediate_ai options may still use local_logic for deterministic prerequisites or same-object setup before adjudication.\n"
            f"12. The client normally spends {ACTION_POINTS_PER_SETTLEMENT} action points before calling you. "
            "For ongoing scenes, keep enough meaningful local_rule interactables and options so the player can usually take several local actions before the next settlement.\n"
            f"13. The playable area is {LIVE_WORLD_WIDTH}x{LIVE_WORLD_HEIGHT} pixels. Every position must use this pixel coordinate space.\n"
            f"14. Keep most x coordinates within {LIVE_WORLD_X_RANGE[0]}-{LIVE_WORLD_X_RANGE[1]} and most y coordinates within {LIVE_WORLD_Y_RANGE[0]}-{LIVE_WORLD_Y_RANGE[1]}.\n"
            "15. Every patrol must be null or an array of at least two coordinate arrays like [[x, y], [x, y]]. Never use coordinate objects.\n"
            "16. When a scene has multiple NPCs or interactables, spread them across left, center, and right areas instead of clustering them in one corner.\n"
            "17. background_image and every image field must be descriptive local asset hints ending in .png. Use short lowercase ASCII names such as rainy_hall.png or security_guard.png.\n"
            "18. Do not return remote URLs, base64, or binary payloads. The client maps asset hints to a local image library.\n"
            "19. narrative must describe the current situation, risk, and the consequences of this round's actions.\n"
            "20. All visible text content must be Simplified Chinese.\n"
        )

    def _build_user_prompt(self, request: AIRequestPayload) -> str:
        payload = {
            "request_type": request.request_type,
            "action_point_rule": {
                "actions_per_settlement": ACTION_POINTS_PER_SETTLEMENT,
                "client_behavior": (
                    "The client applies predictable local_rule logic immediately on the current scene, "
                    "then calls the model after several actions, when no actions remain, "
                    "or immediately after the player selects an option marked immediate_ai."
                ),
                "balancing_goal": (
                    "Keep immediate_ai options rare but meaningful. "
                    "Most options should remain local_rule so the player can act smoothly without waiting on the network."
                ),
            },
            "scene_layout": {
                "coordinate_system": "pixel",
                "playable_area": {"width": LIVE_WORLD_WIDTH, "height": LIVE_WORLD_HEIGHT},
                "safe_x_range": list(LIVE_WORLD_X_RANGE),
                "safe_y_range": list(LIVE_WORLD_Y_RANGE),
                "distribution_rule": (
                    "Spread NPCs and interactables across the room. "
                    "Do not cluster every entity into the top-left corner or a tiny area."
                ),
                "asset_hint_rule": (
                    "background_image and every image field are local asset hints, not URLs. "
                    "Keep them short, lowercase, descriptive, ASCII-only, and ending in .png."
                ),
            },
            "premise": _premise_to_dict(request.premise),
            "settled_history": [_history_record_to_dict(item) for item in request.history],
            "recent_actions": [_history_record_to_dict(item) for item in request.recent_actions],
            "current_scene": None
            if request.current_scene is None
            else scene_to_dict(request.current_scene),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

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
        completed_response: Any = None
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
                final_text = getattr(event, "text", None)
                if isinstance(final_text, str) and final_text and not chunks:
                    chunks.append(final_text)
                continue

            if event_type == "response.completed":
                completed_response = getattr(event, "response", None)
                continue

        return None, completed_response, "".join(chunks)

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

        payload = scene_to_dict(scene)
        for npc in payload["npcs"]:
            npc["position"] = list(self._scale_point(tuple(npc["position"])))
            if npc["patrol"] is not None:
                npc["patrol"] = [list(self._scale_point(tuple(point))) for point in npc["patrol"]]
        for interactable in payload["interactables"]:
            interactable["position"] = list(self._scale_point(tuple(interactable["position"])))
        return load_scene_payload(payload)

    def _scene_points(self, scene: SceneState) -> list[tuple[int, int]]:
        points: list[tuple[int, int]] = []
        for npc in scene.npcs:
            points.append(npc.position)
            if npc.patrol is not None:
                points.extend(npc.patrol)
        for interactable in scene.interactables:
            points.append(interactable.position)
        return points

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
            "OPENAI_API_KEY",
            self._config.provider,
            f"{self._config.provider}_api_key",
        ]
        for key in candidate_keys:
            value = credentials.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return None

    def _initial_scene_cache_key(self, premise: StoryPremise) -> str:
        cache_descriptor = {
            "version": INITIAL_SCENE_CACHE_VERSION,
            "mode": "live" if self._live_enabled else "mock",
            "provider": self._config.provider,
            "base_url": self._config.base_url,
            "model": self._config.model,
            "story_id": premise.story_id,
            "role_id": premise.player_role_id,
            "premise": _premise_to_dict(premise),
        }
        serialized = json.dumps(cache_descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _initial_scene_cache_path(self, premise: StoryPremise) -> Path:
        return self._initial_scene_cache_root / f"{self._initial_scene_cache_key(premise)}.json"

    def _write_initial_scene_cache(self, premise: StoryPremise, scene: SceneState) -> None:
        cache_path = self._initial_scene_cache_path(premise)
        payload = {
            "cache_version": INITIAL_SCENE_CACHE_VERSION,
            "story_id": premise.story_id,
            "role_id": premise.player_role_id,
            "model": self._config.model,
            "source_mode": "Cached Live API" if self._live_enabled else "Cached Mock Story",
            "scene": scene_to_dict(scene),
        }
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return


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
        combined_history = [*request.history, *request.recent_actions]
        action_ids = {record.action_id for record in combined_history}
        latest_action = combined_history[-1].action_id if combined_history else None

        if request.current_scene is None:
            return load_scene_payload(self._initial_scene(request.premise))

        if latest_action == "execute_clean":
            if {"inspect_clue", "prepare_tool", "prepare_support"}.issubset(action_ids):
                return load_scene_payload(
                    self._terminal_scene(
                        request.premise,
                        game_status="player_win",
                        narrative="你把关键痕迹藏进夜色，整场行动像一场被设计好的意外。",
                        ending_text="侦探最终只看到一片混乱的事故现场，没有足够证据把矛头指向你。",
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
                "事情勉强被写成意外，但现场还是留下了几处无法彻底解释的疑点。"
                if status == "special_ending"
                else "你没有准备好足够的掩护，危险动作当场暴露。"
            )
            narrative = (
                "你提前推动了危险方案，结果介于成功与失控之间。"
                if status == "special_ending"
                else "你在关键时刻露出了破绽。"
            )
            return load_scene_payload(
                self._terminal_scene(
                    request.premise,
                    game_status=status,
                    narrative=narrative,
                    ending_text=ending_text,
                )
            )

        scene_payload = scene_to_dict(request.current_scene)
        inside_room = "open_door" in action_ids
        scene_payload["scene"]["background_image"] = (
            "mansion_study_room.png" if inside_room else "rainy_villa_hall.png"
        )
        scene_payload["scene"]["description"] = (
            f"{request.premise.story_title} · 书房内"
            if inside_room
            else f"{request.premise.story_title} · 当前行动阶段"
        )
        scene_payload["narrative"] = self._narrative_for_round(latest_action)
        scene_payload["game_status"] = "ongoing"
        scene_payload["ending_text"] = None
        return load_scene_payload(scene_payload)

    def _initial_scene(self, premise: StoryPremise) -> dict[str, Any]:
        return {
            "scene": {
                "background_image": "rainy_villa_hall.png",
                "bgm": "tense_loop.mp3",
                "description": f"{premise.story_title} · 当前行动阶段",
            },
            "npcs": [
                {
                    "id": "victim",
                    "name": premise.victim_name,
                    "image": "victim.png",
                    "position": [1058, 394],
                    "patrol": None,
                },
                {
                    "id": "detective",
                    "name": premise.detective_name,
                    "image": "detective.png",
                    "position": [214, 308],
                    "patrol": [[180, 296], [286, 320], [240, 358]],
                },
                {
                    "id": "witness",
                    "name": "旁观者",
                    "image": "witness.png",
                    "position": [648, 214],
                    "patrol": [[612, 206], [708, 224]],
                },
            ],
            "interactables": [
                self._interactable(
                    interactable_id="case_clue",
                    name="卷宗夹",
                    image="case_file.png",
                    position=[196, 430],
                    state={"opened": False, "locked": False, "hidden": False, "disabled": False},
                    options=[
                        self._option(
                            "检查线索",
                            "inspect_clue",
                            requires={},
                            set_state={"opened": True, "disabled": True},
                            success_text="你翻开卷宗，确认了关键时间差。",
                        ),
                        self._option("暂时略过", "ignore_clue"),
                    ],
                ),
                self._interactable(
                    interactable_id="primary_tool",
                    name=premise.primary_tool_name,
                    image="tool_case.png",
                    position=[634, 356],
                    state={"opened": False, "locked": True, "hidden": False, "disabled": False},
                    options=[
                        self._option(
                            "解开工具包",
                            "unlock_tool",
                            requires={"locked": True},
                            set_state={"locked": False},
                            success_text="你悄悄解开了工具包的锁扣。",
                            failure_text="工具包已经打开过了。",
                        ),
                        self._option(
                            "布置主要手段",
                            "prepare_tool",
                            requires={"locked": False, "disabled": False},
                            set_state={"opened": True, "disabled": True},
                            success_text="你已经把主要手段安置到位。",
                            failure_text="现在还没法正式布置主手段。",
                        ),
                        self._option("先不处理", "skip_tool"),
                    ],
                ),
                self._interactable(
                    interactable_id="support_tool",
                    name=premise.secondary_tool_name,
                    image="support_kit.png",
                    position=[1110, 266],
                    state={"opened": False, "locked": False, "hidden": False, "disabled": False},
                    options=[
                        self._option(
                            "打开掩护包",
                            "open_support",
                            requires={"opened": False},
                            set_state={"opened": True},
                            success_text="你把掩护工具摊开，开始核对细节。",
                        ),
                        self._option(
                            "准备掩护",
                            "prepare_support",
                            requires={"opened": True, "disabled": False},
                            set_state={"disabled": True},
                            success_text="辅助掩护已经准备完成。",
                            failure_text="先打开掩护包再安排掩护。",
                        ),
                        self._option("维持现状", "skip_support"),
                    ],
                ),
                self._interactable(
                    interactable_id="study_door",
                    name="书房门",
                    image="locked_door.png",
                    position=[836, 210],
                    state={"opened": False, "locked": True, "hidden": False, "disabled": False},
                    options=[
                        self._option("检查门锁", "inspect_lock"),
                        self._option(
                            "撬开门锁",
                            "unlock_door",
                            requires={"locked": True},
                            set_state={"locked": False},
                            success_text="门锁轻轻弹开了一格。",
                            failure_text="这扇门现在不需要再撬。",
                        ),
                        self._option(
                            "推开房门",
                            "open_door",
                            requires={"locked": False, "opened": False},
                            set_state={"opened": True},
                            success_text="你推开书房门，里面比想象中更安静。",
                            failure_text="先解开门锁，或者这扇门已经开了。",
                        ),
                    ],
                ),
                self._interactable(
                    interactable_id="target_window",
                    name="视线盲区",
                    image="window.png",
                    position=[1006, 404],
                    state={"opened": False, "locked": False, "hidden": False, "disabled": False},
                    options=[
                        self._option("继续观察", "wait"),
                        self._option("执行完美方案", "execute_clean", resolution_mode="immediate_ai"),
                        self._option("冒险提前动手", "execute_risky", resolution_mode="immediate_ai"),
                    ],
                ),
            ],
            "narrative": "暴雨压着整座宅邸，你必须先在本地行动点里做好准备，再等待系统结算这轮选择。",
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
                "background_image": "rainy_villa_ending.png",
                "bgm": "ending_resolve.mp3",
                "description": f"{premise.story_title} · 结局",
            },
            "npcs": [
                {
                    "id": "victim",
                    "name": premise.victim_name,
                    "image": "victim.png",
                    "position": [1058, 394],
                    "patrol": None,
                },
                {
                    "id": "detective",
                    "name": premise.detective_name,
                    "image": "detective.png",
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
        image: str,
        position: list[int],
        state: dict[str, bool],
        options: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": interactable_id,
            "name": name,
            "image": image,
            "position": position,
            "state": state,
            "options": options,
        }

    def _option(
        self,
        label: str,
        action_id: str,
        resolution_mode: Literal["local_rule", "immediate_ai"] = "local_rule",
        requires: dict[str, bool] | None = None,
        set_state: dict[str, bool] | None = None,
        success_text: str | None = None,
        failure_text: str | None = None,
    ) -> dict[str, Any]:
        local_logic = None
        if (
            requires is not None
            or set_state is not None
            or success_text is not None
            or failure_text is not None
        ):
            local_logic = {
                "requires_state": requires or {},
                "set_state": set_state or {},
                "success_text": success_text,
                "failure_text": failure_text,
            }
        return {
            "label": label,
            "action_id": action_id,
            "resolution_mode": resolution_mode,
            "local_logic": local_logic,
        }

    def _narrative_for_round(self, latest_action: str | None) -> str:
        narratives = {
            None: "暴雨压着整座宅邸，你只剩下一次把局势推向终局的机会。",
            "inspect_clue": "你确认了卷宗里的关键漏洞，时间窗口比想象中更窄。",
            "unlock_tool": "你先把工具包解开，为真正的布置争取了余地。",
            "prepare_tool": "你已经把主要手段安置到位，只差最后的时机。",
            "open_support": "掩护工具已经摊开，你开始安排更稳妥的退路。",
            "prepare_support": "辅助掩护已经准备完成，现场的可控性明显提升。",
            "inspect_lock": "你重新确认了门锁状态，心里对时机更有把握。",
            "unlock_door": "门锁已经被你处理过，下一步能更安静地进入书房。",
            "open_door": "书房门被悄悄推开，空气里有一丝不正常的安静。",
            "wait": "你暂时按兵不动，观察每个人在房间里的站位变化。",
            "ignore_clue": "你故意略过卷宗，但风险仍在悄悄累积。",
            "skip_tool": "你放弃了主手段，后续选择会变得更加危险。",
            "skip_support": "你没有准备掩护，任何激进行动都会更难收场。",
        }
        return narratives.get(latest_action, "局势正在推进，所有人都离真相更近了一步。")


def _history_record_to_dict(record: ActionRecord) -> dict[str, Any]:
    return {
        "turn_index": record.turn_index,
        "interactable_id": record.interactable_id,
        "interactable_name": record.interactable_name,
        "label": record.label,
        "action_id": record.action_id,
        "resolution_mode": record.resolution_mode,
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
