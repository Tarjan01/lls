from __future__ import annotations

import json
from pathlib import Path

from reverse_detective.story_loader import build_story_premise, load_game_background, load_story_catalog


def test_load_story_catalog_reads_story_json() -> None:
    stories = load_story_catalog()
    story_by_id = {story.id: story for story in stories}

    assert len(stories) >= 2
    assert {"tingtaoge_last_night", "glass_gallery_closing_night"} <= set(story_by_id)
    story = story_by_id["tingtaoge_last_night"]
    assert story.id == "tingtaoge_last_night"
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
    assert premise.primary_tool_name
    assert premise.simulation_briefing == story.simulation_briefing
    assert story.victim_name in premise.initial_goal


def test_load_story_catalog_reads_story_directories(tmp_path: Path) -> None:
    (tmp_path / "game_background.json").write_text(
        json.dumps(
            {
                "game_title": "Reverse Detective",
                "game_subtitle": "demo",
                "operator_name": "江川",
                "background": "背景",
                "briefing": "简介",
                "menu_intro": "菜单",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    story_dir = tmp_path / "demo_story"
    story_dir.mkdir()
    (story_dir / "story.json").write_text(
        json.dumps(
            {
                "id": "demo_story",
                "title": "测试卷宗",
                "subtitle": "目录结构",
                "case": {
                    "location": "测试地点",
                    "setting": "测试设定",
                    "core_case": "测试案情",
                    "opening_hook": "测试开场",
                    "victim": {"name": "死者", "identity": "身份"},
                    "pursuer": {"name": "追查者", "identity": "身份"},
                },
                "roles": [
                    {
                        "id": "demo_role",
                        "title": "角色",
                        "name": "甲",
                        "background": "背景",
                        "motive": "动机",
                        "special_conditions": ["条件"],
                        "signature_tools": [
                            {"name": "工具", "description": "描述"},
                            {"name": "备用", "description": "描述"},
                        ],
                        "hidden_objective": "目标",
                        "strategy_kind": "facility",
                    }
                ],
                "scoring": {
                    "base_score": 60,
                    "evidence_penalties": [],
                    "task_bonuses": [],
                },
                "rankings": [
                    {"rank": "S", "score_range": "90+", "description": "desc"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    stories = load_story_catalog(tmp_path)

    assert len(stories) == 1
    assert stories[0].id == "demo_story"
