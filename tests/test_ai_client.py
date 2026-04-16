from __future__ import annotations

from pathlib import Path

from reverse_detective.ai_client import ReverseDetectiveAIClient, build_default_premise
from reverse_detective.config import AIConfig
from reverse_detective.game_state import PendingChoice


def test_ai_client_uses_mock_mode_when_unconfigured(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="",
            model="gpt-4.1-mini",
            timeout_seconds=30,
            use_mock_when_unconfigured=True,
            fallback_to_mock_on_error=True,
            credentials_path=tmp_path / "missing_credentials.json",
        )
    )

    scene = client.generate_initial_scene(build_default_premise())

    assert client.mode_label == "Mock Story"
    assert scene.game_status == "ongoing"
    assert len(scene.interactables) >= 4


def test_mock_story_can_reach_player_win(tmp_path: Path) -> None:
    client = ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="",
            model="gpt-4.1-mini",
            timeout_seconds=30,
            use_mock_when_unconfigured=True,
            fallback_to_mock_on_error=True,
            credentials_path=tmp_path / "missing_credentials.json",
        )
    )
    premise = build_default_premise()

    scene = client.generate_initial_scene(premise)
    history = []

    for turn_index, interactable_id, interactable_name, label, action_id in [
        (1, "gloves", "皮手套", "戴上手套", "wear_gloves"),
        (2, "knife", "装饰折刀", "把折刀藏进口袋", "take_knife"),
        (3, "fuse_box", "老旧配电箱", "切断电源", "cut_power"),
        (4, "victim_window", "赵铭背后的暗影", "趁黑从背后动手", "darkness_strike"),
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
