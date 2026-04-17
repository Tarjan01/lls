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
from reverse_detective.story_loader import (
    DEFAULT_STORIES_DIR,
    STORY_CACHE_FILE_NAME,
    build_story_premise,
    load_story_catalog,
)


PROMPT_SCHEMA = {
    "scene": {
        "background_image": "mansion_study_room.png",
        "bgm": "crime_suspense_medium",
        "description": "string",
        "bgm_tension": "medium",
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
                    "sfx": "lock_open",
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

SUPPORTED_BGM_CUES = (
    "menu_mystery",
    "crime_suspense_low",
    "crime_suspense_medium",
    "crime_suspense_high",
    "crime_suspense_critical",
    "ending_resolve",
)
SUPPORTED_SFX_CUES = (
    "ui_confirm",
    "ui_success",
    "lock_open",
    "door_open",
    "keys_rattle",
    "metal_hit",
    "wood_slam",
)

LIVE_WORLD_WIDTH = 1280
LIVE_WORLD_HEIGHT = 520
LIVE_WORLD_X_RANGE = (96, LIVE_WORLD_WIDTH - 96)
LIVE_WORLD_Y_RANGE = (140, LIVE_WORLD_HEIGHT - 68)
LIVE_NORMALIZED_COORDINATE_MAX = 120
LIVE_RETRYABLE_REASONS = ("xhigh", "high", "medium", "low")
INITIAL_SCENE_CACHE_VERSION = 1
DEFAULT_INITIAL_SCENE_CACHE_ROOT = Path("~/.reverse_detective/cache/initial_scenes").expanduser()
SHORT_TIMEOUT_OVERALL_BUFFER_SECONDS = 0.5
STREAM_DEADLINE_MIN_BUFFER_SECONDS = 20.0
STREAM_DEADLINE_BUFFER_MULTIPLIER = 1.25


@dataclass(frozen=True, slots=True)
class AIRequestPayload:
    request_type: Literal[
        "initial_scene",
        "round_settlement",
        "forced_immediate_choice",
        "freeform_action",
    ]
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
        self._story_local_cache_enabled = cache_root is None
        self._prefetch_lock = threading.Lock()
        self._prefetch_inflight: set[str] = set()
        self._live_request_lock = threading.Lock()

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
        local_payload = self._read_local_story_cache_entry(premise)
        if local_payload is not None:
            scene = self._load_scene_from_cache_payload(local_payload)
            if scene is not None:
                return scene

        cache_path = self._initial_scene_cache_path(premise)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        return self._load_scene_from_cache_payload(payload)

    def prefetch_initial_scene(self, premise: StoryPremise, *, force: bool = False) -> bool:
        cache_key = self._initial_scene_cache_key(premise)
        cache_path = self._initial_scene_cache_path(premise)
        with self._prefetch_lock:
            if self._prefetch_inflight:
                return False
            if cache_key in self._prefetch_inflight:
                return False
            if (cache_path.exists() or self._read_local_story_cache_entry(premise) is not None) and not force:
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
        request_type: Literal[
            "round_settlement",
            "forced_immediate_choice",
            "freeform_action",
        ] = "round_settlement",
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
        with self._live_request_lock:
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
                    normalized_error = self._normalize_live_error(exc)
                    if not self._is_retryable_live_error(normalized_error):
                        raise normalized_error
                    last_transport_exc = normalized_error
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
            return self._load_scene_payload_with_repair(raw_content)
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
        deadline_seconds = self._live_overall_deadline_seconds(timeout_seconds)

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
        read_timeout = max(10.0, self._live_overall_deadline_seconds(timeout_seconds))
        return httpx.Timeout(
            connect=min(10.0, max(4.0, safe_total / 3)),
            read=read_timeout,
            write=min(20.0, max(6.0, safe_total / 2)),
            pool=10.0,
        )

    def _live_overall_deadline_seconds(self, timeout_seconds: float) -> float:
        safe_total = max(0.0, timeout_seconds)
        if safe_total < 5.0:
            return max(safe_total + SHORT_TIMEOUT_OVERALL_BUFFER_SECONDS, SHORT_TIMEOUT_OVERALL_BUFFER_SECONDS)
        buffer_seconds = max(
            STREAM_DEADLINE_MIN_BUFFER_SECONDS,
            safe_total * STREAM_DEADLINE_BUFFER_MULTIPLIER,
        )
        return safe_total + buffer_seconds

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

    def _normalize_live_error(self, exc: Exception) -> Exception:
        details = str(exc).strip()
        normalized = details.lower()
        concurrency_markers = (
            "并发上限",
            "concurrency",
            "too many concurrent",
            "create a new session",
        )
        if any(marker in details or marker in normalized for marker in concurrency_markers):
            return AIClientError(
                "当前 API Key 同时只能处理一个实时请求。"
                "刚才很可能还有后台预生成或上一条流式请求尚未结束，请稍等片刻后重试。"
            )
        return exc

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
            f"timeout_seconds={self._config.timeout_seconds}，"
            f"stream_deadline_seconds={self._live_overall_deadline_seconds(self._config.timeout_seconds):.0f}，"
            f"且客户端已启用总时限保护。{retry_hint}"
        )

    def _build_system_prompt(self) -> str:
        schema_text = json.dumps(PROMPT_SCHEMA, ensure_ascii=False, separators=(",", ":"))
        return (
            "You generate scene JSON for a reverse-detective game. "
            "Return exactly one JSON object and nothing else. "
            "Do not return markdown, explanations, or code fences. "
            "The client performs predictable local interactions locally and only asks you for the initial scene, "
            "or when the player chooses an option marked immediate_ai, "
            "or when the player submits a freeform custom action outside the visible options, "
            "or when the player manually requests story progression because the current deterministic setup phase is exhausted. "
            "You must return the next settled scene after adjudicating the whole pending action batch. "
            "The JSON must match this schema exactly with no missing or extra root fields:\n"
            f"{schema_text}\n"
            "Requirements:\n"
            "1. game_status must be one of ongoing, player_win, player_lose, special_ending.\n"
            "2. ending_text must be null when game_status is ongoing, otherwise it must contain a concrete ending text.\n"
            "3. Every interactable must include state with opened, locked, hidden, disabled booleans.\n"
            "4. Every option must include resolution_mode, local_logic, and may include an sfx cue id. resolution_mode must be local_rule or immediate_ai.\n"
            "5. Prefer local_rule by default. Only mark an option as immediate_ai when it is a true key decision that can sharply change risk, social reaction, exposure, evidence, time jump, location jump, or branch outcome.\n"
            "6. Keep immediate_ai as a minority of the total options, but do not collapse the scene into one mandatory chokepoint. Most ongoing scenes should expose two to four meaningful key decision vectors across the scene.\n"
            "7. Good local_rule examples: unlocking, opening, searching, observing, picking up known tools, simple setup, repeatable checks, deterministic positioning and disguise work.\n"
            "8. Good immediate_ai examples: committing the crime, bluffing an NPC, moving a body, destroying evidence under pressure, triggering alarms, forcing confrontation, choosing whether to flee, or any action whose outcome depends on dynamic reactions.\n"
            "9. local_logic can only describe same-object logic through requires_state and set_state, using only opened, locked, hidden, disabled.\n"
            "10. IMPORTANT: if local_logic is an object, it must contain exactly four keys: requires_state, set_state, success_text, failure_text. Never return a partial local_logic object. If any key is unused, still include it with {} or null.\n"
            "11. Every local_rule option MUST include a non-null local_logic object with concrete success_text and failure_text. Even observation, waiting, hesitation, or scouting actions must explain what the player learned, changed, or why repeating it gives no extra benefit.\n"
            "12. Every option must either produce explicit execution feedback on the current scene or immediately hand control to the next AI-adjudicated branch. Never include filler actions that only say the action happened.\n"
            "13. immediate_ai options may still use local_logic for deterministic prerequisites or same-object setup before adjudication.\n"
            "14. Plan a complete 3-6 beat story arc internally. Let scenes shift across time and locations when key decisions resolve, while preserving continuity from prior actions.\n"
            "15. Avoid single-path scenes. Most ongoing scenes should present at least two distinct forward branches with different risk, evidence, NPC reaction, timing, or location consequences. Only use a single mandatory immediate_ai choice when the scene is close to a terminal outcome.\n"
            f"16. The playable area is {LIVE_WORLD_WIDTH}x{LIVE_WORLD_HEIGHT} pixels. Every position must use this pixel coordinate space.\n"
            f"17. Keep most x coordinates within {LIVE_WORLD_X_RANGE[0]}-{LIVE_WORLD_X_RANGE[1]} and most y coordinates within {LIVE_WORLD_Y_RANGE[0]}-{LIVE_WORLD_Y_RANGE[1]}.\n"
            "18. Every patrol must be null or an array of at least two coordinate arrays like [[x, y], [x, y]]. Never use coordinate objects.\n"
            "19. When a scene has multiple NPCs or interactables, spread them across left, center, and right areas instead of clustering them in one corner.\n"
            "20. background_image and every image field must be descriptive local asset hints ending in .png. Use short lowercase ASCII names such as rainy_villa_hall.png, detective.png, or tool_case.png.\n"
            "21. The bundled art library is 2.5D and stage-like: side-view or front-view rooms, upright characters, and front/side props with clear flat silhouettes.\n"
            "22. Never imply top-down, overhead, bird's-eye, minimap, tactical-grid, or isometric map art. Asset hints must fit the local side/front-view library.\n"
            "23. Prefer asset hints close to the bundled library, such as rainy_villa_hall.png, rainy_villa_ending.png, front_gallery.png, detective.png, victim.png, witness.png, security_guard.png, tool_case.png, support_kit.png, guest_register.png, locked_door.png, open_door.png, or window.png.\n"
            "24. Do not return remote URLs, base64, or binary payloads. The client maps asset hints to a local image library.\n"
            f"25. scene.bgm must be a local music cue id, not a filename or URL. Prefer one of {', '.join(SUPPORTED_BGM_CUES)}.\n"
            "26. scene.bgm_tension must be one of low, medium, high, critical and should reflect suspense intensity.\n"
            f"27. options[].sfx should be null or a local sound cue id. Prefer one of {', '.join(SUPPORTED_SFX_CUES)}.\n"
            "28. This is a crime and suspense game. Avoid cheerful or relaxed in-game music. Prefer noir, suspense, stealth, pressure, and dread.\n"
            "29. narrative must describe the current situation, current time or phase when relevant, immediate risk, and the consequences of the pending key decisions.\n"
            "30. All visible text content must be Simplified Chinese.\n"
        )

    def _build_user_prompt(self, request: AIRequestPayload) -> str:
        payload = {
            "request_type": request.request_type,
            "decision_flow": {
                "client_behavior": (
                    "The client applies predictable local_rule logic immediately on the current scene and stores those actions locally. "
                    "It calls the model only on initial scene generation, when the player selects an immediate_ai option, "
                    "when the player submits a freeform custom action, "
                    "or when the player manually requests progression because the deterministic setup phase has run out of meaningful actions."
                ),
                "balancing_goal": (
                    "Keep immediate_ai as a minority of all visible options, but avoid a single mandatory chokepoint. "
                    "Most ongoing scenes should still offer two or three distinct branching decision vectors with clearly different consequences."
                ),
                "feedback_goal": (
                    "Every local_rule option must give explicit execution feedback. "
                    "Observation or wait actions should still state what the player learned, what changed, or why the window did not improve."
                ),
                "story_goal": (
                    "Design a coherent multi-scene crime plan with time progression, location changes, and escalating pressure. "
                    "Each returned scene should feel like one beat inside a larger plotted case."
                ),
                "branching_goal": (
                    "Prefer multiple concurrent key decisions across different interactables or NPCs. "
                    "Do not make every branch converge into the same immediate outcome unless the story is nearly over."
                ),
            },
            "scene_layout": {
                "coordinate_system": "pixel",
                "playable_area": {"width": LIVE_WORLD_WIDTH, "height": LIVE_WORLD_HEIGHT},
                "safe_x_range": list(LIVE_WORLD_X_RANGE),
                "safe_y_range": list(LIVE_WORLD_Y_RANGE),
                "distribution_rule": (
                    "Spread NPCs and interactables across the room like a side-view stage. "
                    "Do not cluster every entity into the top-left corner or a tiny area."
                ),
                "asset_hint_rule": (
                    "background_image and every image field are local asset hints, not URLs. "
                    "Keep them short, lowercase, descriptive, ASCII-only, and ending in .png. "
                    "Prefer the bundled 2.5D side/front-view library with upright characters and front/side props. "
                    "Never imply top-down, overhead, bird's-eye, or isometric art."
                ),
            },
            "audio_guidance": {
                "bgm_cues": list(SUPPORTED_BGM_CUES),
                "sfx_cues": list(SUPPORTED_SFX_CUES),
                "suspense_scale": ["low", "medium", "high", "critical"],
                "cue_rule": (
                    "Return cue ids only. Do not return remote audio URLs, base64, or binary data. "
                    "Return both scene.bgm and scene.bgm_tension. "
                    "Keep menu music mysterious, keep in-game music suspenseful, and scale intensity from low to critical based on danger and time pressure. "
                    "Avoid lighthearted or relaxed crime-scene music. "
                    "Prefer ending_resolve only for terminal scenes, and short sfx ids on options when a local effect is obvious."
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
            return self._load_scene_payload_with_repair(candidate)
        except Exception:
            return None

    def _load_scene_payload_with_repair(self, payload: str | dict[str, Any]) -> SceneState:
        try:
            return self._normalize_scene_layout(load_scene_payload(payload))
        except Exception:
            repaired_payload = self._repair_scene_payload_schema(payload)
            return self._normalize_scene_layout(load_scene_payload(repaired_payload))

    def _repair_scene_payload_schema(self, payload: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload, str):
            raw_payload = json.loads(payload)
        else:
            raw_payload = dict(payload)

        if not isinstance(raw_payload, dict):
            return raw_payload

        interactables = raw_payload.get("interactables")
        if isinstance(interactables, list):
            repaired_interactables: list[Any] = []
            for interactable in interactables:
                if not isinstance(interactable, dict):
                    repaired_interactables.append(interactable)
                    continue

                repaired_interactable = dict(interactable)
                state = repaired_interactable.get("state")
                if isinstance(state, dict):
                    repaired_interactable["state"] = {
                        "opened": bool(state.get("opened", False)),
                        "locked": bool(state.get("locked", False)),
                        "hidden": bool(state.get("hidden", False)),
                        "disabled": bool(state.get("disabled", False)),
                    }

                options = repaired_interactable.get("options")
                if isinstance(options, list):
                    repaired_options: list[Any] = []
                    for option in options:
                        if not isinstance(option, dict):
                            repaired_options.append(option)
                            continue
                        repaired_option = dict(option)
                        resolution_mode = repaired_option.get("resolution_mode", "local_rule")
                        if not isinstance(resolution_mode, str) or not resolution_mode.strip():
                            resolution_mode = "local_rule"
                        resolution_mode = resolution_mode.strip()
                        repaired_option["resolution_mode"] = resolution_mode

                        option_label = repaired_option.get("label")
                        if not isinstance(option_label, str) or not option_label.strip():
                            option_label = "当前动作"
                        option_label = option_label.strip()

                        raw_logic = repaired_option.get("local_logic")
                        if isinstance(raw_logic, dict):
                            repaired_option["local_logic"] = self._repair_local_logic_payload(
                                raw_logic,
                                option_label=option_label,
                                resolution_mode=resolution_mode,
                            )
                        elif resolution_mode == "local_rule":
                            repaired_option["local_logic"] = self._repair_local_logic_payload(
                                {},
                                option_label=option_label,
                                resolution_mode=resolution_mode,
                            )
                        repaired_options.append(repaired_option)
                    repaired_interactable["options"] = repaired_options

                repaired_interactables.append(repaired_interactable)

            raw_payload["interactables"] = repaired_interactables

        return raw_payload

    def _repair_local_logic_payload(
        self,
        logic: dict[str, Any],
        *,
        option_label: str,
        resolution_mode: str,
    ) -> dict[str, Any]:
        requires_state = logic.get("requires_state")
        set_state = logic.get("set_state")
        return {
            "requires_state": dict(requires_state) if isinstance(requires_state, dict) else {},
            "set_state": dict(set_state) if isinstance(set_state, dict) else {},
            "success_text": self._repair_feedback_text(
                logic.get("success_text"),
                option_label=option_label,
                resolution_mode=resolution_mode,
                success=True,
            ),
            "failure_text": self._repair_feedback_text(
                logic.get("failure_text"),
                option_label=option_label,
                resolution_mode=resolution_mode,
                success=False,
            ),
        }

    def _repair_feedback_text(
        self,
        value: Any,
        *,
        option_label: str,
        resolution_mode: str,
        success: bool,
    ) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()

        if resolution_mode == "immediate_ai":
            if success:
                return f"你选择了“{option_label}”，局势会立刻根据这一步发生变化。"
            return f"当前条件不足，暂时无法触发“{option_label}”。"

        if success:
            return f"你执行了“{option_label}”，并得到了一条可继续利用的反馈。"
        return f"当前条件不足，暂时无法执行“{option_label}”。"

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
        payload = self._build_initial_scene_cache_payload(premise, scene)
        self._write_runtime_initial_scene_cache(premise, payload)
        self._write_local_story_cache(premise, payload)

    def _build_initial_scene_cache_payload(
        self,
        premise: StoryPremise,
        scene: SceneState,
    ) -> dict[str, Any]:
        return {
            "cache_version": INITIAL_SCENE_CACHE_VERSION,
            "story_id": premise.story_id,
            "role_id": premise.player_role_id,
            "model": self._config.model,
            "source_mode": "Cached Live API" if self._live_enabled else "Cached Mock Story",
            "scene": scene_to_dict(scene),
        }

    def _write_runtime_initial_scene_cache(
        self,
        premise: StoryPremise,
        payload: dict[str, Any],
    ) -> None:
        cache_path = self._initial_scene_cache_path(premise)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return

    def _local_story_cache_path(self, premise: StoryPremise) -> Path:
        return DEFAULT_STORIES_DIR / premise.story_id / STORY_CACHE_FILE_NAME

    def _read_local_story_cache_entry(self, premise: StoryPremise) -> dict[str, Any] | None:
        if not self._story_local_cache_enabled:
            return None

        cache_path = self._local_story_cache_path(premise)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(payload, dict):
            return None

        entries = payload.get("entries")
        if isinstance(entries, dict):
            entry = entries.get(premise.player_role_id)
            if isinstance(entry, dict):
                return entry

        if payload.get("role_id") == premise.player_role_id and isinstance(payload.get("scene"), dict):
            return payload
        return None

    def _write_local_story_cache(self, premise: StoryPremise, payload: dict[str, Any]) -> None:
        if not self._story_local_cache_enabled:
            return

        cache_path = self._local_story_cache_path(premise)
        existing_entries: dict[str, Any] = {}
        if cache_path.exists():
            try:
                existing_payload = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing_payload = {}
            if isinstance(existing_payload, dict) and isinstance(existing_payload.get("entries"), dict):
                existing_entries = {
                    key: value
                    for key, value in existing_payload["entries"].items()
                    if isinstance(key, str) and isinstance(value, dict)
                }

        existing_entries[premise.player_role_id] = payload
        file_payload = {
            "cache_version": INITIAL_SCENE_CACHE_VERSION,
            "story_id": premise.story_id,
            "entries": existing_entries,
        }
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(file_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return

    def _load_scene_from_cache_payload(self, payload: Any) -> SceneState | None:
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
        latest_record = combined_history[-1] if combined_history else None
        latest_action = latest_record.action_id if latest_record is not None else None

        if request.current_scene is None:
            return load_scene_payload(self._initial_scene(request.premise))

        if latest_action == "player_freeform_action":
            return load_scene_payload(self._freeform_scene(request, latest_record))

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

        if latest_action == "stage_alibi":
            if {"read_witness_route", "inspect_clue"}.issubset(action_ids):
                return load_scene_payload(self._alibi_scene(request.premise))
            return load_scene_payload(
                self._terminal_scene(
                    request.premise,
                    game_status="player_lose",
                    narrative="你仓促布置不在场证明，但证词和时间线根本对不上。",
                    ending_text="侦探顺着证人的说法倒推出你的行动轨迹，谎言在第一轮盘问里就被拆穿。",
                )
            )

        if latest_action == "lure_witness":
            status = "special_ending" if {"read_witness_route", "prepare_support"}.issubset(action_ids) else "player_lose"
            narrative = (
                "你成功把证人的注意力拽离盲区，却也让整层楼的节奏提前失衡。"
                if status == "special_ending"
                else "你想诱导证人离开，可动作太急，反而把自己暴露给了走廊里的视线。"
            )
            ending_text = (
                "你换来了一个勉强可用的行动窗口，但整起案件仍留下了可疑的空白。"
                if status == "special_ending"
                else "证人记住了你刻意引导的动作，侦探很快把这段异常行为串成了证据链。"
            )
            return load_scene_payload(
                self._terminal_scene(
                    request.premise,
                    game_status=status,
                    narrative=narrative,
                    ending_text=ending_text,
                )
            )

        if latest_action == "pin_blame":
            if {"plant_register", "inspect_clue", "prepare_support"}.issubset(action_ids):
                return load_scene_payload(
                    self._terminal_scene(
                        request.premise,
                        game_status="player_win",
                        narrative="你把时间线、证词和来客记录扣成了一张完整的伪网，怀疑被稳稳引向了错误对象。",
                        ending_text="侦探在错误的方向上越查越深，而你已经带着完整的不在场证明退回了安全位置。",
                    )
                )
            return load_scene_payload(
                self._terminal_scene(
                    request.premise,
                    game_status="special_ending",
                    narrative="你成功转移了一部分怀疑，但伪造痕迹仍让案件多出几分说不清的别扭。",
                    ending_text="案子暂时没有落到你头上，可侦探对那本登记簿始终保留着一点迟迟没放下的怀疑。",
                )
            )

        if latest_action == "retreat_clean":
            status = "special_ending" if {"check_exit", "prepare_support"}.issubset(action_ids) else "player_lose"
            narrative = (
                "你收束了整场布局，趁人群和雨声掩护把自己从现场里抹了出去。"
                if status == "special_ending"
                else "你想干净撤离，可通道和掩护都没有准备妥当，离场动作显得过于突兀。"
            )
            ending_text = (
                "你没有把怀疑完全转嫁出去，但至少成功把自己藏进了混乱的尾声。"
                if status == "special_ending"
                else "侦探注意到你离场的时间点过于巧合，撤离本身成了最醒目的异常。"
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
        scene_payload["scene"]["bgm"] = "crime_suspense_high" if inside_room else "crime_suspense_medium"
        scene_payload["scene"]["bgm_tension"] = "high" if inside_room else "medium"
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
                "bgm": "crime_suspense_medium",
                "description": f"{premise.story_title} · 当前行动阶段",
                "bgm_tension": "medium",
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
                            requires={"opened": False},
                            set_state={"opened": True},
                            success_text="你翻开卷宗，确认了关键时间差。",
                            failure_text="你已经把卷宗里的关键页记住了。",
                        ),
                        self._option(
                            "暂时略过",
                            "ignore_clue",
                            success_text="你决定先不碰卷宗，把注意力留给更紧迫的布置。",
                            failure_text="你已经做出了暂缓处理卷宗的决定。",
                        ),
                    ],
                ),
                self._interactable(
                    interactable_id="witness_route",
                    name="走廊动线",
                    image="corridor_watch.png",
                    position=[394, 196],
                    state={"opened": False, "locked": False, "hidden": False, "disabled": False},
                    options=[
                        self._option(
                            "观察证人动线",
                            "read_witness_route",
                            requires={"opened": False},
                            set_state={"opened": True},
                            success_text="你记住了旁观者在走廊上的折返节奏，盲区真正出现的时机终于清晰了。",
                            failure_text="你已经摸清了这条走廊上的往返规律。",
                        ),
                        self._option(
                            "提前布置不在场证明",
                            "stage_alibi",
                            resolution_mode="immediate_ai",
                            requires={"opened": True, "disabled": False},
                            set_state={"disabled": True},
                            success_text="你决定先把自己放进无辜者的位置，再看这套说辞是否经得起追问。",
                            failure_text="先摸清证人的动线，再决定如何利用这段空档。",
                        ),
                        self._option(
                            "诱导证人离开盲区",
                            "lure_witness",
                            resolution_mode="immediate_ai",
                            requires={"opened": True, "disabled": False},
                            set_state={"disabled": True},
                            success_text="你开始引导证人的注意力偏离真正的盲区，准备赌一次节奏失衡。",
                            failure_text="你还没掌握证人的出入节奏，贸然引导只会让自己暴露。",
                        ),
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
                        self._option(
                            "先不处理",
                            "skip_tool",
                            success_text="你暂时压住了动手冲动，决定把风险留到更合适的时机。",
                            failure_text="你已经选择继续按兵不动。",
                        ),
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
                        self._option(
                            "维持现状",
                            "skip_support",
                            success_text="你决定暂不动用这组掩护，把它留作更靠后的保险。",
                            failure_text="这组掩护目前仍被你原样保留。",
                        ),
                    ],
                ),
                self._interactable(
                    interactable_id="study_door",
                    name="书房门",
                    image="locked_door.png",
                    position=[836, 210],
                    state={"opened": False, "locked": True, "hidden": False, "disabled": False},
                    options=[
                        self._option(
                            "检查门锁",
                            "inspect_lock",
                            success_text="你重新确认了门锁结构和开合声，心里对进门时机更有把握。",
                            failure_text="你刚刚已经仔细确认过这把门锁了。",
                        ),
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
                        self._option(
                            "继续观察",
                            "wait",
                            success_text="你继续压低存在感，记录每个人的站位和下一次错身的时间点。",
                            failure_text="你已经把这一轮站位变化看得足够清楚了。",
                        ),
                        self._option(
                            "执行完美方案",
                            "execute_clean",
                            resolution_mode="immediate_ai",
                            success_text="你决定按原计划进入最稳的一条线，接下来只看局势会不会如你预估般收束。",
                            failure_text="现在还不是推出完美方案的时机。",
                        ),
                        self._option(
                            "冒险提前动手",
                            "execute_risky",
                            resolution_mode="immediate_ai",
                            success_text="你决定抢在所有准备彻底到位前动手，把结果押在一个更窄的窗口上。",
                            failure_text="此刻贸然推进只会让风险比你能承受的更高。",
                        ),
                    ],
                ),
            ],
            "narrative": "暴雨压着整座宅邸，你必须先完成确定性的准备动作，再在关键决策点推动剧情进入下一阶段。",
            "game_status": "ongoing",
            "ending_text": None,
        }

    def _alibi_scene(self, premise: StoryPremise) -> dict[str, Any]:
        return {
            "scene": {
                "background_image": "front_gallery.png",
                "bgm": "crime_suspense_low",
                "description": f"{premise.story_title} · 前厅假象",
                "bgm_tension": "low",
            },
            "npcs": [
                {
                    "id": "detective",
                    "name": premise.detective_name,
                    "image": "detective.png",
                    "position": [262, 304],
                    "patrol": [[222, 296], [338, 320], [296, 360]],
                },
                {
                    "id": "witness",
                    "name": "旁观者",
                    "image": "witness.png",
                    "position": [924, 238],
                    "patrol": [[882, 228], [980, 248]],
                },
            ],
            "interactables": [
                self._interactable(
                    interactable_id="guest_register",
                    name="来客登记簿",
                    image="guest_register.png",
                    position=[438, 392],
                    state={"opened": False, "locked": False, "hidden": False, "disabled": False},
                    options=[
                        self._option(
                            "补上一笔到访记录",
                            "plant_register",
                            requires={"opened": False},
                            set_state={"opened": True},
                            success_text="你在登记簿上补了一笔足以支撑说辞的到访记录。",
                            failure_text="这本登记簿已经被你动过，继续添改只会增加破绽。",
                        ),
                        self._option(
                            "把怀疑引向他人",
                            "pin_blame",
                            resolution_mode="immediate_ai",
                            requires={"opened": True, "disabled": False},
                            set_state={"disabled": True},
                            success_text="你决定借这本登记簿把视线推向另一个更显眼的人。",
                            failure_text="先把能自圆其说的登记记录补好，再谈得上转移怀疑。",
                        ),
                    ],
                ),
                self._interactable(
                    interactable_id="service_passage",
                    name="侧门通道",
                    image="service_passage.png",
                    position=[986, 334],
                    state={"opened": False, "locked": False, "hidden": False, "disabled": False},
                    options=[
                        self._option(
                            "确认退路",
                            "check_exit",
                            requires={"opened": False},
                            set_state={"opened": True},
                            success_text="你试过了侧门铰链的声音，确认还能悄无声息地脱离现场。",
                            failure_text="你已经摸清这条退路的状况了。",
                        ),
                        self._option(
                            "趁混乱撤离",
                            "retreat_clean",
                            resolution_mode="immediate_ai",
                            requires={"opened": True, "disabled": False},
                            set_state={"disabled": True},
                            success_text="你决定把整场布局收束成一次干净的离场，把怀疑留在身后。",
                            failure_text="先确认退路，再决定是否马上撤离。",
                        ),
                    ],
                ),
            ],
            "narrative": "不在场证明已经开始成形，前厅里到处都是能被利用也能反噬你的细节。你需要决定，是把怀疑推给别人，还是把自己悄悄从现场抹去。",
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
                "bgm": "ending_resolve",
                "description": f"{premise.story_title} · 结局",
                "bgm_tension": "critical" if game_status == "player_lose" else "high",
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

    def _freeform_scene(self, request: AIRequestPayload, latest_record: ActionRecord | None) -> dict[str, Any]:
        scene_payload = scene_to_dict(request.current_scene) if request.current_scene is not None else self._initial_scene(request.premise)
        freeform_text = ""
        if latest_record is not None and latest_record.freeform_text:
            freeform_text = latest_record.freeform_text.strip()
        lowered = freeform_text.lower()

        if any(token in freeform_text for token in ("撤", "逃", "离开", "撤离", "脱身")):
            return self._terminal_scene(
                request.premise,
                game_status="special_ending",
                narrative=f"你临时提出了“{freeform_text}”的方案，并抓住了一次并不完美但足够脱身的窗口。",
                ending_text="你提前结束了这场重演。虽然侦探仍保留疑点，但你至少没有被当场锁死在现场。",
            )

        if any(token in freeform_text for token in ("杀", "推下", "行凶", "下毒", "勒", "刺")):
            prepared = {"prepare_tool", "prepare_support"} & {record.action_id for record in [*request.history, *request.recent_actions]}
            status = "special_ending" if prepared else "player_lose"
            return self._terminal_scene(
                request.premise,
                game_status=status,
                narrative=f"你越过预设选项，直接尝试“{freeform_text}”。局面被瞬间推到了不可逆的阶段。",
                ending_text=(
                    "行动勉强被你压住了场面，但仍留下了很难彻底洗掉的疑点。"
                    if status == "special_ending"
                    else "你贸然推进决定性动作，侦探和现场反应都来得比你预想更快。"
                ),
            )

        scene_payload["scene"]["bgm"] = "crime_suspense_high"
        scene_payload["scene"]["bgm_tension"] = "high"
        scene_payload["narrative"] = (
            f"你尝试了自由行动“{freeform_text or '未命名行动'}”。"
            "这一举动让现场关系立刻变得更紧绷，接下来的每个决定都更容易引发连锁反应。"
        )
        scene_payload["game_status"] = "ongoing"
        scene_payload["ending_text"] = None
        return scene_payload

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
        sfx: str | None = None,
    ) -> dict[str, Any]:
        local_logic = None
        if (
            requires is not None
            or set_state is not None
            or success_text is not None
            or failure_text is not None
            or resolution_mode == "local_rule"
        ):
            local_logic = {
                "requires_state": requires or {},
                "set_state": set_state or {},
                "success_text": success_text
                or (
                    f"你执行了“{label}”，并得到了一条可继续利用的反馈。"
                    if resolution_mode == "local_rule"
                    else None
                ),
                "failure_text": failure_text
                or (
                    f"当前条件不足，暂时无法执行“{label}”。"
                    if resolution_mode == "local_rule"
                    else None
                ),
            }
        return {
            "label": label,
            "action_id": action_id,
            "resolution_mode": resolution_mode,
            "sfx": sfx or self._default_sfx_for_action(action_id, resolution_mode),
            "local_logic": local_logic,
        }

    def _default_sfx_for_action(
        self,
        action_id: str,
        resolution_mode: Literal["local_rule", "immediate_ai"],
    ) -> str | None:
        mapping = {
            "unlock_tool": "lock_open",
            "prepare_tool": "keys_rattle",
            "open_support": "keys_rattle",
            "prepare_support": "ui_success",
            "inspect_lock": "ui_confirm",
            "unlock_door": "lock_open",
            "open_door": "door_open",
            "wait": "ui_confirm",
            "inspect_clue": "ui_confirm",
            "ignore_clue": "ui_confirm",
            "read_witness_route": "ui_confirm",
            "stage_alibi": "metal_hit",
            "lure_witness": "metal_hit",
            "execute_clean": "wood_slam",
            "execute_risky": "metal_hit",
            "plant_register": "ui_confirm",
            "pin_blame": "metal_hit",
            "check_exit": "door_open",
            "retreat_clean": "wood_slam",
        }
        if action_id in mapping:
            return mapping[action_id]
        if resolution_mode == "immediate_ai":
            return "metal_hit"
        return "ui_confirm"

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
        "source": record.source,
        "freeform_text": record.freeform_text,
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
