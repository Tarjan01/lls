from __future__ import annotations

from reverse_detective.story_loader import build_story_premise, load_game_background, load_story_catalog


def test_load_story_catalog_reads_story_json() -> None:
    stories = load_story_catalog()
    story_by_id = {story.id: story for story in stories}

    assert len(stories) >= 2
    assert {"tingtaoge_last_night", "glass_gallery_closing_night"} <= set(story_by_id)
    story = story_by_id["tingtaoge_last_night"]
    assert story.id == "tingtaoge_last_night"
    assert story.title == "迷雾山庄的最后一夜"
    assert len(story.roles) == 4
    assert story.roles[0].primary_tool_name
    assert story.simulation_operator_name == "江川"
    assert story.simulation_briefing


def test_load_game_background_reads_global_background_file() -> None:
    background = load_game_background()

    assert background.operator_name == "江川"
    assert "扮演凶手" in background.background
    assert "案件模拟台" in background.menu_intro


def test_build_story_premise_uses_selected_role() -> None:
    stories = {story.id: story for story in load_story_catalog()}
    story = stories["tingtaoge_last_night"]

    premise = build_story_premise(story, "su_man")

    assert premise.story_id == story.id
    assert premise.player_role_id == "su_man"
    assert premise.player_role_name == "商业对手·苏曼"
    assert premise.primary_tool_name == "“幽灵”病毒"
    assert premise.simulation_briefing == story.simulation_briefing
    assert "赵万山" in premise.initial_goal
