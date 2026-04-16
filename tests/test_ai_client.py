from __future__ import annotations

from pathlib import Path

from reverse_detective.ai_client import AIRequestPayload, ReverseDetectiveAIClient, build_default_premise
from reverse_detective.config import AIConfig
from reverse_detective.game_state import PendingChoice


def test_ai_client_uses_mock_mode_when_unconfigured(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="",
            model="gpt-4.1-mini",
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
    assert scene.npcs[0].name == "赵万山"


def test_mock_story_can_reach_player_win(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="",
            model="gpt-4.1-mini",
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
        (1, "case_clue", "祖宅变卖文件", "确认地契与变卖安排", "inspect_clue"),
        (2, "primary_tool", "安神茶", "把安神茶送进备用茶盏", "prepare_tool"),
        (3, "support_tool", "总控平板", "用总控平板接管书房设备", "prepare_support"),
        (4, "target_window", "锁死书房后的无声死角", "锁门后引爆安神茶与设备异常", "execute_clean"),
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


def test_build_response_input_uses_message_list_for_live_api(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="https://apikey.soxio.me/openai",
            model="gpt-5.4",
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
    assert response_input[0]["role"] == "system"
    assert response_input[1]["role"] == "user"
    assert isinstance(response_input[0]["content"], str)
    assert isinstance(response_input[1]["content"], str)
