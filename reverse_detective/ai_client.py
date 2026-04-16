"""AI scene generation entrypoint for the Reverse Detective demo."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
import threading
from typing import Any
from urllib.request import urlopen

from reverse_detective.config import AIConfig
from reverse_detective.game_state import PendingChoice
from reverse_detective.models import ActionRecord, Interactable, NPC, SceneState, StoryPremise
from reverse_detective.scene_loader import load_scene_payload, scene_to_dict
from reverse_detective.story_loader import build_story_premise, load_story_catalog
from reverse_detective.utils.assets import (
    DEFAULT_ASSET_CACHE_ROOT,
    ensure_asset_parent,
    resolve_cached_asset_path,
)


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
IMAGE_GENERATION_TIMEOUT_SECONDS = 20.0
IMAGE_GENERATION_QUALITY = "low"
IMAGE_OUTPUT_FORMAT = "png"


@dataclass(frozen=True, slots=True)
class AIRequestPayload:
    premise: StoryPremise
    current_scene: SceneState | None
    history: tuple[ActionRecord, ...]
    latest_choice: PendingChoice | None


@dataclass(frozen=True, slots=True)
class AssetGenerationRequest:
    kind: str
    asset_id: str
    prompt: str
    size: str
    background: str


class AIClientError(RuntimeError):
    """Raised when the configured AI provider cannot generate a valid scene."""


class ReverseDetectiveAIClient:
    """Facade for live OpenAI-compatible requests with a local mock fallback."""

    def __init__(self, config: AIConfig, asset_root: Path | None = None):
        self._config = config
        self._mock_engine = _MockStoryEngine()
        self._api_key = self._load_api_key(config.credentials_path)
        self._asset_root = (asset_root or DEFAULT_ASSET_CACHE_ROOT).resolve()
        self._asset_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rd-assets")
        self._asset_jobs_lock = threading.Lock()
        self._pending_asset_jobs: set[tuple[str, str]] = set()
        self._live_enabled = bool(config.base_url and config.model and self._api_key)
        self._last_mode_label = "Live API" if self._live_enabled else "Mock Story"

        if not self._live_enabled and not config.use_mock_when_unconfigured:
            raise AIClientError(
                "AI provider is not fully configured and mock mode has been disabled."
            )

    @property
    def mode_label(self) -> str:
        return self._last_mode_label

    def close(self) -> None:
        self._asset_executor.shutdown(wait=False, cancel_futures=True)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

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
            scene = self._normalize_scene_layout(streamed_scene)
            self._schedule_scene_assets(request.premise, scene)
            return scene

        raw_content = self._extract_response_content(response, streamed_text)
        try:
            scene = self._normalize_scene_layout(load_scene_payload(raw_content))
        except Exception as exc:
            raise AIClientError(f"Live AI returned invalid scene JSON: {exc}") from exc

        self._schedule_scene_assets(request.premise, scene)
        return scene

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
            "7. background_image and every image field must be stable reusable asset IDs ending in .png, using short lowercase ASCII with underscores.\n"
            "8. Reuse the same asset ID across turns when the same room, NPC, or item is still visually the same. Use a new asset ID only when the visual subject changes.\n"
            "9. narrative must describe the current situation and risk.\n"
            "10. All visible text content must be Simplified Chinese.\n"
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
                "asset_id_rule": (
                    "background_image and every image field are reusable asset IDs, not local file paths. "
                    "Keep them short, lowercase, descriptive, ASCII-only, and ending in .png."
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

    def _schedule_scene_assets(self, premise: StoryPremise, scene: SceneState) -> None:
        for asset_request in self._build_asset_requests(premise, scene):
            cache_path = resolve_cached_asset_path(
                asset_request.kind,
                asset_request.asset_id,
                self._asset_root,
            )
            if cache_path is None or cache_path.exists():
                continue

            asset_key = (asset_request.kind, asset_request.asset_id)
            with self._asset_jobs_lock:
                if asset_key in self._pending_asset_jobs:
                    continue
                self._pending_asset_jobs.add(asset_key)

            self._asset_executor.submit(self._generate_scene_asset, asset_request)

    def _build_asset_requests(
        self,
        premise: StoryPremise,
        scene: SceneState,
    ) -> list[AssetGenerationRequest]:
        requests = [
            AssetGenerationRequest(
                kind="background",
                asset_id=scene.scene.background_image,
                prompt=self._build_background_asset_prompt(premise, scene),
                size="1536x1024",
                background="opaque",
            )
        ]

        requests.extend(
            AssetGenerationRequest(
                kind="npc",
                asset_id=npc.image,
                prompt=self._build_npc_asset_prompt(premise, scene, npc),
                size="1024x1024",
                background="transparent",
            )
            for npc in scene.npcs
        )
        requests.extend(
            AssetGenerationRequest(
                kind="interactable",
                asset_id=interactable.image,
                prompt=self._build_interactable_asset_prompt(premise, scene, interactable),
                size="1024x1024",
                background="transparent",
            )
            for interactable in scene.interactables
        )
        return requests

    def _generate_scene_asset(self, asset_request: AssetGenerationRequest) -> None:
        asset_key = (asset_request.kind, asset_request.asset_id)
        try:
            cache_path = resolve_cached_asset_path(
                asset_request.kind,
                asset_request.asset_id,
                self._asset_root,
            )
            if cache_path is None or cache_path.exists():
                return

            image_bytes = self._request_generated_image_bytes(asset_request)
            ensure_asset_parent(cache_path).write_bytes(image_bytes)
        except Exception:
            return
        finally:
            with self._asset_jobs_lock:
                self._pending_asset_jobs.discard(asset_key)

    def _request_generated_image_bytes(self, asset_request: AssetGenerationRequest) -> bytes:
        response_tool_error: Exception | None = None
        try:
            return self._request_image_bytes_from_responses_tool(asset_request)
        except Exception as exc:
            response_tool_error = exc

        image_api_error: Exception | None = None
        try:
            return self._request_image_bytes_from_images_api(asset_request)
        except Exception as exc:
            image_api_error = exc

        if response_tool_error is not None and image_api_error is not None:
            raise AIClientError(
                "Image generation failed via responses tool and images API: "
                f"{response_tool_error}; fallback: {image_api_error}"
            ) from image_api_error
        if response_tool_error is not None:
            raise AIClientError(f"Image generation failed: {response_tool_error}") from response_tool_error
        if image_api_error is not None:
            raise AIClientError(f"Image generation failed: {image_api_error}") from image_api_error
        raise AIClientError("Image generation response did not contain an image payload.")

    def _request_image_bytes_from_responses_tool(
        self,
        asset_request: AssetGenerationRequest,
    ) -> bytes:
        from openai import OpenAI

        client = OpenAI(
            api_key=self._api_key,
            base_url=self._config.base_url,
            timeout=min(self._config.timeout_seconds, IMAGE_GENERATION_TIMEOUT_SECONDS),
        )

        tools_attempts = (
            {
                "tools": [
                    {
                        "type": "image_generation",
                        "model": self._config.image_model,
                        "background": asset_request.background,
                        "quality": IMAGE_GENERATION_QUALITY,
                        "size": asset_request.size,
                        "output_format": IMAGE_OUTPUT_FORMAT,
                    }
                ],
                "tool_choice": {"type": "image_generation"},
            },
            {
                "tools": [
                    {
                        "type": "image_generation",
                        "background": asset_request.background,
                        "quality": IMAGE_GENERATION_QUALITY,
                        "size": asset_request.size,
                        "output_format": IMAGE_OUTPUT_FORMAT,
                    }
                ],
                "tool_choice": {"type": "image_generation"},
            },
            {
                "tools": [{"type": "image_generation"}],
            },
        )

        last_error: Exception | None = None
        for attempt_kwargs in tools_attempts:
            try:
                with client.responses.stream(
                    model=self._config.model,
                    input=[
                        {
                            "type": "message",
                            "role": "user",
                            "content": asset_request.prompt,
                        }
                    ],
                    store=not self._config.disable_response_storage,
                    **attempt_kwargs,
                ) as stream:
                    return self._consume_image_generation_stream(stream)
            except Exception as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise AIClientError(f"Responses image tool failed: {last_error}") from last_error
        raise AIClientError("Responses image tool did not return an image.")

    def _request_image_bytes_from_images_api(self, asset_request: AssetGenerationRequest) -> bytes:
        from openai import OpenAI

        client = OpenAI(
            api_key=self._api_key,
            base_url=self._config.base_url,
            timeout=min(self._config.timeout_seconds, IMAGE_GENERATION_TIMEOUT_SECONDS),
        )
        base_kwargs = {
            "model": self._config.image_model,
            "prompt": asset_request.prompt,
            "size": asset_request.size,
        }
        attempts = (
            {
                "background": asset_request.background,
                "quality": IMAGE_GENERATION_QUALITY,
                "output_format": IMAGE_OUTPUT_FORMAT,
                "response_format": "b64_json",
            },
            {
                "background": asset_request.background,
                "quality": IMAGE_GENERATION_QUALITY,
                "output_format": IMAGE_OUTPUT_FORMAT,
                "response_format": "url",
            },
            {
                "output_format": IMAGE_OUTPUT_FORMAT,
                "response_format": "b64_json",
            },
            {
                "response_format": "url",
            },
        )

        last_error: Exception | None = None
        for attempt_kwargs in attempts:
            try:
                response = client.images.generate(**base_kwargs, **attempt_kwargs)
                image_data = self._extract_generated_image_data(response)
                b64_payload = self._read_image_field(image_data, "b64_json")
                if b64_payload:
                    return base64.b64decode(b64_payload)

                image_url = self._read_image_field(image_data, "url")
                if image_url:
                    return self._download_binary(image_url)
            except Exception as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise AIClientError(f"Images API failed: {last_error}") from last_error
        raise AIClientError("Images API response did not contain an image payload.")

    def _consume_image_generation_stream(self, stream: Any) -> bytes:
        response: Any = None
        for event in stream:
            event_type = getattr(event, "type", None)
            if event_type == "response.output_item.done":
                image_bytes = self._extract_image_bytes_from_output_item(getattr(event, "item", None))
                if image_bytes is not None:
                    return image_bytes
                continue

            if event_type == "response.completed":
                response = getattr(event, "response", None)

        image_bytes = self._extract_image_bytes_from_response(response)
        if image_bytes is not None:
            return image_bytes
        raise AIClientError("Responses image tool stream did not return an image.")

    def _extract_image_bytes_from_response(self, response: Any) -> bytes | None:
        output_items = getattr(response, "output", None)
        if isinstance(output_items, list):
            for item in output_items:
                image_bytes = self._extract_image_bytes_from_output_item(item)
                if image_bytes is not None:
                    return image_bytes
        return None

    def _extract_image_bytes_from_output_item(self, item: Any) -> bytes | None:
        if item is None:
            return None

        item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
        if item_type != "image_generation_call":
            return None

        raw_result = item.get("result") if isinstance(item, dict) else getattr(item, "result", None)
        if isinstance(raw_result, str) and raw_result.strip():
            return base64.b64decode(raw_result)
        return None

    def _extract_generated_image_data(self, response: Any) -> Any:
        data = getattr(response, "data", None)
        if isinstance(data, list) and data:
            return data[0]

        if isinstance(response, dict):
            raw_data = response.get("data")
            if isinstance(raw_data, list) and raw_data:
                return raw_data[0]

        raise AIClientError("Image generation response did not contain image data.")

    def _read_image_field(self, image_data: Any, field_name: str) -> str:
        if isinstance(image_data, dict):
            value = image_data.get(field_name)
        else:
            value = getattr(image_data, field_name, None)
        if isinstance(value, str):
            return value.strip()
        return ""

    def _download_binary(self, url: str) -> bytes:
        with urlopen(
            url,
            timeout=min(self._config.timeout_seconds, IMAGE_GENERATION_TIMEOUT_SECONDS),
        ) as response:
            payload = response.read()
        if not isinstance(payload, bytes) or not payload:
            raise AIClientError("Downloaded image payload was empty.")
        return payload

    def _build_background_asset_prompt(self, premise: StoryPremise, scene: SceneState) -> str:
        return (
            "Create a 2.5D mystery game background illustration. "
            "Stylized semi-realistic digital painting, cinematic lighting, no text, no UI, no watermark. "
            f"Asset ID: {scene.scene.background_image}. "
            f"Story title: {premise.story_title}. "
            f"Setting: {premise.setting}. "
            f"Scene description: {scene.scene.description}. "
            "Leave clear open floor space for player movement in the middle and foreground. "
            "Interior composition for a suspenseful detective simulation."
        )

    def _build_npc_asset_prompt(
        self,
        premise: StoryPremise,
        scene: SceneState,
        npc: NPC,
    ) -> str:
        role_hint = "supporting character"
        if npc.name == premise.detective_name:
            role_hint = f"detective, identity: {premise.detective_identity}"
        elif npc.name == premise.victim_name:
            role_hint = f"victim, identity: {premise.victim_identity}"

        return (
            "Create a full-body game character sprite for a 2.5D mystery game. "
            "Transparent background, centered subject, readable silhouette, no text, no watermark. "
            f"Asset ID: {npc.image}. "
            f"Character name: {npc.name}. "
            f"Role: {role_hint}. "
            f"Story title: {premise.story_title}. "
            f"Scene location: {scene.scene.description}. "
            "Stylized semi-realistic illustration suitable for compositing into a side-view scene."
        )

    def _build_interactable_asset_prompt(
        self,
        premise: StoryPremise,
        scene: SceneState,
        interactable: Interactable,
    ) -> str:
        return (
            "Create a prop sprite for a 2.5D mystery game. "
            "Transparent background, isolated object, no text, no watermark, readable at small size. "
            f"Asset ID: {interactable.image}. "
            f"Object name: {interactable.name}. "
            f"Story title: {premise.story_title}. "
            f"Scene location: {scene.scene.description}. "
            f"Setting: {premise.setting}. "
            "Stylized semi-realistic illustration for an interactive clue object."
        )

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
