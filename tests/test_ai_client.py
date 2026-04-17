from __future__ import annotations

from pathlib import Path
import threading
import time

import httpx
import pytest

from reverse_detective.ai_client import AIRequestPayload, ReverseDetectiveAIClient, build_default_premise
from reverse_detective.config import AIConfig
from reverse_detective.game_state import PendingChoice
from reverse_detective.scene_loader import load_scene_payload


def _build_config(tmp_path: Path, **overrides: object) -> AIConfig:
    defaults: dict[str, object] = {
        "provider": "crs",
        "base_url": "",
        "model": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "timeout_seconds": 30,
        "disable_response_storage": True,
        "use_mock_when_unconfigured": True,
        "fallback_to_mock_on_error": True,
        "credentials_path": tmp_path / "credentials.json",
    }
    defaults.update(overrides)
    return AIConfig(**defaults)


def test_ai_client_uses_mock_mode_when_unconfigured(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(_build_config(tmp_path), cache_root=tmp_path / "cache")

    scene = client.generate_initial_scene(build_default_premise())

    assert client.mode_label == "Mock Story"
    assert scene.game_status == "ongoing"
    assert len(scene.interactables) >= 3


def test_mock_story_can_reach_player_win(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(_build_config(tmp_path), cache_root=tmp_path / "cache")
    premise = build_default_premise()

    scene = client.generate_initial_scene(premise)
    history = []

    for turn_index, interactable_id, interactable_name, label, action_id in [
        (1, "case_clue", "卷宗夹", "检查线索", "inspect_clue"),
        (2, "primary_tool", "主手段", "布置主要手段", "prepare_tool"),
        (3, "support_tool", "掩护工具", "准备掩护", "prepare_support"),
        (4, "target_window", "盲区", "执行完美方案", "execute_clean"),
    ]:
        choice = PendingChoice(
            turn_index=turn_index,
            interactable_id=interactable_id,
            interactable_name=interactable_name,
            label=label,
            action_id=action_id,
            resolution_mode="immediate_ai" if action_id.startswith("execute_") else "local_rule",
        )
        scene = client.generate_next_scene(premise, scene, history, choice)
        history.append(choice.to_record())

    assert scene.game_status == "player_win"
    assert scene.ending_text is not None


def test_extract_response_content_reads_output_text(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(_build_config(tmp_path), cache_root=tmp_path / "cache")

    class FakeResponse:
        output_text = '{"scene": {}}'

    assert client._extract_response_content(FakeResponse()) == '{"scene": {}}'


def test_extract_response_content_prefers_streamed_text(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(_build_config(tmp_path), cache_root=tmp_path / "cache")

    class FakeResponse:
        output_text = ""

    assert client._extract_response_content(FakeResponse(), '{"scene": {}}') == '{"scene": {}}'


def test_build_response_input_uses_message_list_for_live_api(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        _build_config(
            tmp_path,
            base_url="https://apikey.soxio.me/openai",
        ),
        cache_root=tmp_path / "cache",
    )
    premise = build_default_premise()

    response_input = client._build_response_input(
        AIRequestPayload(
            request_type="initial_scene",
            premise=premise,
            current_scene=None,
            history=(),
            recent_actions=(),
        )
    )

    assert isinstance(response_input, list)
    assert response_input[0]["role"] == "developer"
    assert response_input[1]["role"] == "user"
    assert isinstance(response_input[0]["content"], str)
    assert isinstance(response_input[1]["content"], str)
    assert '"scene_layout"' in response_input[1]["content"]
    assert '"coordinate_system":"pixel"' in response_input[1]["content"]
    assert '"balancing_goal"' in response_input[1]["content"]
    assert '"recent_actions"' in response_input[1]["content"]


def test_live_scene_uses_streaming_responses_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text('{"api_key":"test-key"}', encoding="utf-8")

    captured: dict[str, object] = {}
    scene_json = (
        '{"scene":{"background_image":"bg.png","bgm":"bgm.mp3","description":"scene"},'
        '"npcs":[],"interactables":[{"id":"obj","name":"item","image":"obj.png",'
        '"position":[640,260],"options":[{"label":"inspect","action_id":"inspect"}]}],'
        '"narrative":"story","game_status":"ongoing","ending_text":null}'
    )

    class FakeEvent:
        type = "response.output_text.delta"

        def __init__(self, delta: str):
            self.delta = delta

    class FakeStream:
        def __enter__(self) -> "FakeStream":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def __iter__(self):
            yield FakeEvent(scene_json)

    class FakeResponses:
        def stream(self, **kwargs):
            captured.update(kwargs)
            return FakeStream()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    client = ReverseDetectiveAIClient(
        _build_config(
            tmp_path,
            base_url="https://apikey.soxio.me/openai",
            use_mock_when_unconfigured=False,
            fallback_to_mock_on_error=False,
            credentials_path=credentials_path,
        ),
        cache_root=tmp_path / "cache",
    )

    try:
        scene = client.generate_initial_scene(build_default_premise())

        assert scene.game_status == "ongoing"
        assert scene.interactables[0].options[0].action_id == "inspect"
        assert captured["model"] == "gpt-5.4"
        assert captured["store"] is False
        assert captured["reasoning"] == {"effort": "xhigh"}
        assert isinstance(captured["input"], list)
    finally:
        client.close()


def test_live_scene_scales_small_grid_coordinates_to_pixel_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text('{"api_key":"test-key"}', encoding="utf-8")

    scene_json = (
        '{"scene":{"background_image":"bg.png","bgm":"bgm.mp3","description":"scene"},'
        '"npcs":[{"id":"detective","name":"Detective","image":"npc.png","position":[38,74],'
        '"patrol":[[38,74],[52,70],[60,78]]}],"interactables":'
        '[{"id":"glass","name":"Display","image":"glass.png","position":[82,64],'
        '"options":[{"label":"inspect","action_id":"inspect"}]}],'
        '"narrative":"story","game_status":"ongoing","ending_text":null}'
    )

    class FakeEvent:
        type = "response.output_text.delta"

        def __init__(self, delta: str):
            self.delta = delta

    class FakeStream:
        def __enter__(self) -> "FakeStream":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def __iter__(self):
            yield FakeEvent(scene_json)

    class FakeResponses:
        def stream(self, **kwargs):
            return FakeStream()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    client = ReverseDetectiveAIClient(
        _build_config(
            tmp_path,
            base_url="https://apikey.soxio.me/openai",
            use_mock_when_unconfigured=False,
            fallback_to_mock_on_error=False,
            credentials_path=credentials_path,
        ),
        cache_root=tmp_path / "cache",
    )

    try:
        scene = client.generate_initial_scene(build_default_premise())

        assert scene.npcs[0].position == (509, 371)
        assert scene.npcs[0].patrol == ((509, 371), (662, 358), (749, 383))
        assert scene.interactables[0].position == (988, 340)
    finally:
        client.close()


def test_consume_response_stream_does_not_require_response_completed(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(_build_config(tmp_path), cache_root=tmp_path / "cache")
    client._try_parse_streamed_scene = lambda _: None  # type: ignore[method-assign]

    class FakeEvent:
        type = "response.output_text.delta"

        def __init__(self, delta: str):
            self.delta = delta

    class FakeStream:
        def __iter__(self):
            yield FakeEvent('{"scene":')
            yield FakeEvent(' {"description": "partial"}}')

    streamed_scene, response, streamed_text = client._consume_response_stream(FakeStream())

    assert streamed_scene is None
    assert response is None
    assert streamed_text == '{"scene": {"description": "partial"}}'


def test_live_scene_retries_once_after_timeout_then_succeeds(tmp_path: Path) -> None:
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text('{"api_key":"test-key"}', encoding="utf-8")
    client = ReverseDetectiveAIClient(
        _build_config(
            tmp_path,
            base_url="https://apikey.soxio.me/openai",
            use_mock_when_unconfigured=False,
            fallback_to_mock_on_error=False,
            credentials_path=credentials_path,
        ),
        cache_root=tmp_path / "cache",
    )
    attempts: list[tuple[str, float]] = []
    scene = load_scene_payload(
        {
            "scene": {
                "background_image": "bg.png",
                "bgm": "bgm.mp3",
                "description": "scene",
            },
            "npcs": [],
            "interactables": [],
            "narrative": "story",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    def fake_stream_live_scene(request, *, reasoning_effort: str, timeout_seconds: float):
        attempts.append((reasoning_effort, timeout_seconds))
        if len(attempts) == 1:
            raise httpx.ReadTimeout("The read operation timed out")
        return scene

    client._stream_live_scene = fake_stream_live_scene  # type: ignore[method-assign]

    result = client.generate_initial_scene(build_default_premise())

    assert result.scene.description == "scene"
    assert attempts == [("xhigh", 30), ("medium", 30)]


def test_live_transport_error_message_includes_base_url_and_hint(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        _build_config(tmp_path, base_url="https://apikey.soxio.me/openai"),
        cache_root=tmp_path / "cache",
    )

    message = client._format_live_transport_error(httpx.ReadTimeout("The read operation timed out"))

    assert "https://apikey.soxio.me/openai" in message
    assert "timeout_seconds=30" in message
    assert "stream_deadline_seconds=" in message
    assert "降到 medium" in message


def test_live_error_normalizes_concurrency_limit_message(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(_build_config(tmp_path), cache_root=tmp_path / "cache")

    error = client._normalize_live_error(RuntimeError("请求已超出当前 API Key 的并发上限，请创建新会话后重试。"))

    assert isinstance(error, Exception)
    assert "同时只能处理一个实时请求" in str(error)


def test_scene_payload_repair_fills_missing_local_logic_keys(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(_build_config(tmp_path), cache_root=tmp_path / "cache")

    scene = client._load_scene_payload_with_repair(
        {
            "scene": {
                "background_image": "bg.png",
                "bgm": "bgm.mp3",
                "description": "repair",
            },
            "npcs": [],
            "interactables": [
                {
                    "id": "door",
                    "name": "门",
                    "image": "door.png",
                    "position": [320, 240],
                    "state": {
                        "opened": False,
                        "locked": True,
                        "hidden": False,
                        "disabled": False,
                    },
                    "options": [
                        {
                            "label": "开锁",
                            "action_id": "unlock",
                            "resolution_mode": "local_rule",
                            "local_logic": {
                                "requires_state": {"locked": True},
                                "success_text": "锁开了。",
                            },
                        }
                    ],
                }
            ],
            "narrative": "测试修复缺失的 local_logic 键。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    assert scene.interactables[0].options[0].local_logic is not None
    assert scene.interactables[0].options[0].local_logic.set_state == {}
    assert scene.interactables[0].options[0].local_logic.failure_text is None


def test_live_timeout_expands_stream_read_deadline_for_normal_requests(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(_build_config(tmp_path), cache_root=tmp_path / "cache")

    deadline_seconds = client._live_overall_deadline_seconds(45)
    timeout = client._build_live_timeout(45)

    assert deadline_seconds > 45
    assert timeout.read == deadline_seconds


def test_live_scene_deadline_stops_hung_stream(tmp_path: Path) -> None:
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text('{"api_key":"test-key"}', encoding="utf-8")
    client = ReverseDetectiveAIClient(
        _build_config(
            tmp_path,
            base_url="https://apikey.soxio.me/openai",
            timeout_seconds=0.1,
            use_mock_when_unconfigured=False,
            fallback_to_mock_on_error=False,
            credentials_path=credentials_path,
        ),
        cache_root=tmp_path / "cache",
    )

    def fake_stream_live_scene(request, *, reasoning_effort: str, timeout_seconds: float):
        time.sleep(1.5)
        raise AssertionError("background thread should be ignored after deadline")

    client._stream_live_scene = fake_stream_live_scene  # type: ignore[method-assign]
    client._live_attempt_plan = lambda: [("xhigh", 0.1)]  # type: ignore[method-assign]

    start = time.monotonic()
    with pytest.raises(Exception, match="overall deadline|总时限保护"):
        client.generate_initial_scene(build_default_premise())
    elapsed = time.monotonic() - start

    assert elapsed < 1.2


def test_live_requests_are_serialized_for_single_api_key(tmp_path: Path) -> None:
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text('{"api_key":"test-key"}', encoding="utf-8")
    client = ReverseDetectiveAIClient(
        _build_config(
            tmp_path,
            base_url="https://apikey.soxio.me/openai",
            use_mock_when_unconfigured=False,
            fallback_to_mock_on_error=False,
            credentials_path=credentials_path,
        ),
        cache_root=tmp_path / "cache",
    )
    scene = load_scene_payload(
        {
            "scene": {
                "background_image": "bg.png",
                "bgm": "bgm.mp3",
                "description": "serialized",
            },
            "npcs": [],
            "interactables": [],
            "narrative": "story",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    active_calls = 0
    max_active_calls = 0
    guard = threading.Lock()

    def fake_stream_live_scene_with_deadline(request, *, reasoning_effort: str, timeout_seconds: float):
        nonlocal active_calls, max_active_calls
        with guard:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
        time.sleep(0.15)
        with guard:
            active_calls -= 1
        return scene

    client._stream_live_scene_with_deadline = fake_stream_live_scene_with_deadline  # type: ignore[method-assign]
    client._live_attempt_plan = lambda: [("xhigh", 30)]  # type: ignore[method-assign]

    threads = [
        threading.Thread(target=client.generate_initial_scene, args=(build_default_premise(),))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert max_active_calls == 1


def test_initial_scene_cache_roundtrip_loads_saved_scene(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    client = ReverseDetectiveAIClient(_build_config(tmp_path), cache_root=cache_root)
    premise = build_default_premise()

    scene = client.generate_initial_scene(premise)
    cached_scene = client.load_cached_initial_scene(premise)

    assert cached_scene is not None
    assert cached_scene.scene.description == scene.scene.description
    assert client.mode_label.startswith("Cached")
