from __future__ import annotations

from reverse_detective.story_loader import build_story_premise, load_story_catalog


def test_load_story_catalog_reads_story_json() -> None:
    stories = load_story_catalog()

    assert len(stories) >= 1
    story = stories[0]
    assert story.id == "tingtaoge_last_night"
    assert story.title == "迷雾山庄的最后一夜"
    assert len(story.roles) == 4
    assert story.roles[0].primary_tool_name


def test_build_story_premise_uses_selected_role() -> None:
    story = load_story_catalog()[0]

    premise = build_story_premise(story, "su_man")

    assert premise.story_id == story.id
    assert premise.player_role_id == "su_man"
    assert premise.player_role_name == "商业对手·苏曼"
    assert premise.primary_tool_name == "“幽灵”病毒"
    assert "赵万山" in premise.initial_goal
