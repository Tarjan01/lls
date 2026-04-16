from __future__ import annotations

import base64
from pathlib import Path

import pytest

from reverse_detective.ai_client import (
    AIRequestPayload,
    AssetGenerationRequest,
    ReverseDetectiveAIClient,
    build_default_premise,
)
from reverse_detective.config import AIConfig
from reverse_detective.game_state import PendingChoice
from reverse_detective.utils.assets import resolve_cached_asset_path


def test_ai_client_uses_mock_mode_when_unconfigured(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="",
            model="gpt-4.1-mini",
            image_model="gpt-image-1",
            reasoning_effort="high",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=True,
            fallback_to_mock_on_error=True,
            credentials_path=tmp_path / "missing_credentials.json",
        )
    )

    scene = client.generate_initial_scene(build_default_premise())

    assert client.mode_label == "Mock Story"
    assert scene.game_status == "ongoing"
    assert len(scene.interactables) >= 3


def test_mock_story_can_reach_player_win(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="",
            model="gpt-4.1-mini",
            image_model="gpt-image-1",
            reasoning_effort="high",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=True,
            fallback_to_mock_on_error=True,
            credentials_path=tmp_path / "missing_credentials.json",
        )
    )
    premise = build_default_premise()

    scene = client.generate_initial_scene(premise)
    history = []

    for turn_index, interactable_id, interactable_name, label, action_id in [
        (1, "case_clue", "case clue", "inspect clue", "inspect_clue"),
        (2, "primary_tool", "primary tool", "prepare tool", "prepare_tool"),
        (3, "support_tool", "support tool", "prepare support", "prepare_support"),
        (4, "target_window", "target window", "execute clean", "execute_clean"),
    ]:
        choice = PendingChoice(
            turn_index=turn_index,
            interactable_id=interactable_id,
            interactable_name=interactable_name,
            label=label,
            action_id=action_id,
        )
        scene = client.generate_next_scene(premise, scene, history, choice)
        history.append(choice.to_record())

    assert scene.game_status == "player_win"
    assert scene.ending_text is not None


def test_extract_response_content_reads_output_text(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="",
            model="gpt-5.4",
            image_model="gpt-image-1",
            reasoning_effort="xhigh",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=True,
            fallback_to_mock_on_error=True,
            credentials_path=tmp_path / "missing_credentials.json",
        )
    )

    class FakeResponse:
        output_text = '{"scene": {}}'

    assert client._extract_response_content(FakeResponse()) == '{"scene": {}}'


def test_extract_response_content_prefers_streamed_text(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="",
            model="gpt-5.4",
            image_model="gpt-image-1",
            reasoning_effort="xhigh",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=True,
            fallback_to_mock_on_error=True,
            credentials_path=tmp_path / "missing_credentials.json",
        )
    )

    class FakeResponse:
        output_text = ""

    assert client._extract_response_content(FakeResponse(), '{"scene": {}}') == '{"scene": {}}'


def test_build_response_input_uses_message_list_for_live_api(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="https://apikey.soxio.me/openai",
            model="gpt-5.4",
            image_model="gpt-image-1",
            reasoning_effort="xhigh",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=True,
            fallback_to_mock_on_error=True,
            credentials_path=tmp_path / "credentials.json",
        )
    )
    premise = build_default_premise()

    response_input = client._build_response_input(
        AIRequestPayload(
            premise=premise,
            current_scene=None,
            history=(),
            latest_choice=None,
        )
    )

    assert isinstance(response_input, list)
    assert response_input[0]["role"] == "developer"
    assert response_input[1]["role"] == "user"
    assert isinstance(response_input[0]["content"], str)
    assert isinstance(response_input[1]["content"], str)
    assert '"scene_layout"' in response_input[1]["content"]
    assert '"coordinate_system": "pixel"' in response_input[1]["content"]


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

    class FakeResponse:
        output_text = ""

    class FakeStream:
        def __enter__(self) -> "FakeStream":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def __iter__(self):
            yield FakeEvent(scene_json)

        def get_final_response(self) -> FakeResponse:
            return FakeResponse()

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
        AIConfig(
            provider="crs",
            base_url="https://apikey.soxio.me/openai",
            model="gpt-5.4",
            image_model="gpt-image-1",
            reasoning_effort="xhigh",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=False,
            fallback_to_mock_on_error=False,
            credentials_path=credentials_path,
        )
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


def test_live_scene_returns_early_when_streamed_json_is_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text('{"api_key":"test-key"}', encoding="utf-8")

    scene_json = (
        '{"scene":{"background_image":"bg.png","bgm":"bgm.mp3","description":"scene"},'
        '"npcs":[],"interactables":[{"id":"obj","name":"item","image":"obj.png",'
        '"position":[640,260],"options":[{"label":"inspect","action_id":"inspect"}]}],'
        '"narrative":"story","game_status":"ongoing","ending_text":null}'
    )
    call_state = {"final_called": False}

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
            yield FakeEvent("THIS SHOULD NEVER BE READ")

        def get_final_response(self):
            call_state["final_called"] = True
            raise AssertionError("get_final_response should not be called after early parse")

    class FakeResponses:
        def stream(self, **kwargs):
            return FakeStream()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="https://apikey.soxio.me/openai",
            model="gpt-5.4",
            image_model="gpt-image-1",
            reasoning_effort="xhigh",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=False,
            fallback_to_mock_on_error=False,
            credentials_path=credentials_path,
        )
    )

    try:
        scene = client.generate_initial_scene(build_default_premise())

        assert scene.interactables[0].position == (640, 260)
        assert call_state["final_called"] is False
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

        def get_final_response(self):
            raise AssertionError("get_final_response should not be called after early parse")

    class FakeResponses:
        def stream(self, **kwargs):
            return FakeStream()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="https://apikey.soxio.me/openai",
            model="gpt-5.4",
            image_model="gpt-image-1",
            reasoning_effort="xhigh",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=False,
            fallback_to_mock_on_error=False,
            credentials_path=credentials_path,
        )
    )

    try:
        scene = client.generate_initial_scene(build_default_premise())

        assert scene.npcs[0].position == (509, 371)
        assert scene.npcs[0].patrol == ((509, 371), (662, 358), (749, 383))
        assert scene.interactables[0].position == (988, 340)
    finally:
        client.close()


def test_consume_response_stream_does_not_require_response_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="https://apikey.soxio.me/openai",
            model="gpt-5.4",
            image_model="gpt-image-1",
            reasoning_effort="xhigh",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=True,
            fallback_to_mock_on_error=True,
            credentials_path=tmp_path / "credentials.json",
        )
    )

    monkeypatch.setattr(client, "_try_parse_streamed_scene", lambda _: None)

    class FakeEvent:
        type = "response.output_text.delta"

        def __init__(self, delta: str):
            self.delta = delta

    class FakeStream:
        def __iter__(self):
            yield FakeEvent('{"scene":')
            yield FakeEvent(' {"description": "partial"}}')

        def get_final_response(self):
            raise AssertionError("get_final_response should not be required")

    streamed_scene, response, streamed_text = client._consume_response_stream(FakeStream())

    assert streamed_scene is None
    assert response is None
    assert streamed_text == '{"scene": {"description": "partial"}}'


def test_generate_scene_asset_writes_cached_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text('{"api_key":"test-key"}', encoding="utf-8")

    captured: dict[str, object] = {}

    class FakeImageData:
        b64_json = base64.b64encode(b"fake-image-bytes").decode("ascii")
        url = None

    class FakeImageResponse:
        data = [FakeImageData()]

    class FakeImages:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return FakeImageResponse()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.images = FakeImages()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    asset_root = tmp_path / "assets"
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="https://apikey.soxio.me/openai",
            model="gpt-5.4",
            image_model="gpt-image-1",
            reasoning_effort="xhigh",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=False,
            fallback_to_mock_on_error=False,
            credentials_path=credentials_path,
        ),
        asset_root=asset_root,
    )

    request = AssetGenerationRequest(
        kind="background",
        asset_id="bg_test_case.png",
        prompt="test prompt",
        size="1536x1024",
        background="opaque",
    )

    try:
        client._generate_scene_asset(request)

        cached_path = resolve_cached_asset_path("background", request.asset_id, asset_root)
        assert cached_path is not None
        assert cached_path.read_bytes() == b"fake-image-bytes"
        assert captured["model"] == "gpt-image-1"
        assert captured["response_format"] == "b64_json"
        assert captured["background"] == "opaque"
    finally:
        client.close()


def test_request_generated_image_bytes_prefers_responses_image_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text('{"api_key":"test-key"}', encoding="utf-8")

    class FakeEvent:
        type = "response.output_item.done"

        def __init__(self, payload: str):
            self.item = {"type": "image_generation_call", "result": payload}

    class FakeStream:
        def __enter__(self) -> "FakeStream":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def __iter__(self):
            yield FakeEvent(base64.b64encode(b"tool-image").decode("ascii"))

    class FakeResponses:
        def stream(self, **kwargs):
            return FakeStream()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="https://apikey.soxio.me/openai",
            model="gpt-5.4",
            image_model="gpt-image-1",
            reasoning_effort="xhigh",
            timeout_seconds=30,
            disable_response_storage=True,
            use_mock_when_unconfigured=False,
            fallback_to_mock_on_error=False,
            credentials_path=credentials_path,
        )
    )

    request = AssetGenerationRequest(
        kind="background",
        asset_id="bg_test_case.png",
        prompt="test prompt",
        size="1536x1024",
        background="opaque",
    )

    try:
        assert client._request_generated_image_bytes(request) == b"tool-image"
    finally:
        client.close()
