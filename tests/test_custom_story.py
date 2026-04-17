from __future__ import annotations

import json
from pathlib import Path

import pygame
import pytest

from reverse_detective.app import GameApp
from reverse_detective.config import load_config
from reverse_detective.custom_story import CustomStoryDraft, write_custom_story
from reverse_detective.story_loader import load_story_catalog


def _write_background(root: Path) -> None:
    (root / "game_background.json").write_text(
        json.dumps(
            {
                "game_title": "Reverse Detective",
                "game_subtitle": "demo",
                "operator_name": "江川",
                "background": "背景",
                "briefing": "简报",
                "menu_intro": "菜单介绍",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_seed_story(root: Path) -> None:
    story_dir = root / "seed_story"
    story_dir.mkdir(parents=True)
    (story_dir / "story.json").write_text(
        json.dumps(
            {
                "id": "seed_story",
                "title": "种子卷宗",
                "subtitle": "初始卷宗",
                "case": {
                    "location": "测试地点",
                    "setting": "测试设定",
                    "core_case": "测试案情",
                    "opening_hook": "测试开场",
                    "victim": {"name": "测试死者", "identity": "测试身份"},
                    "pursuer": {"name": "江川", "identity": "侦探"},
                },
                "roles": [
                    {
                        "id": "seed_role",
                        "title": "身份",
                        "name": "甲",
                        "background": "背景",
                        "motive": "动机",
                        "special_conditions": ["条件"],
                        "signature_tools": [
                            {"name": "工具一", "description": "描述"},
                            {"name": "工具二", "description": "描述"},
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
            indent=2,
        ),
        encoding="utf-8",
    )


def test_write_custom_story_creates_valid_story_directory(tmp_path: Path) -> None:
    _write_background(tmp_path)

    draft = CustomStoryDraft(
        title="钟楼停摆之夜",
        subtitle="玩家自定义卷宗",
        location="旧城区钟楼",
        setting="暴雨夜里，钟楼封闭检修，值守人员和来访者都被困在塔内。",
        core_case="馆长在钟楼顶层坠落身亡，现场记录与证词互相冲突。",
        opening_hook="最后一次报时结束后，整座钟楼突然停摆，所有人都意识到出事了。",
        victim_name="杜衡",
        victim_identity="钟楼基金会馆长",
        detective_identity="负责复盘此案的侦探",
    )

    story_path, story_id = write_custom_story(
        draft,
        detective_name="江川",
        stories_dir=tmp_path,
    )

    assert story_path.is_file()
    assert story_path.parent.name == story_id

    stories = load_story_catalog(tmp_path)

    assert len(stories) == 1
    assert stories[0].id == story_id
    assert stories[0].title == "钟楼停摆之夜"
    assert len(stories[0].roles) == 4


def test_game_app_can_save_custom_story_from_menu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    _write_background(tmp_path)
    _write_seed_story(tmp_path)

    app = GameApp(load_config(), stories_dir=tmp_path)
    try:
        app._handle_keydown(pygame.K_DOWN)
        app._handle_keydown(pygame.K_RETURN)

        assert app._mode == "custom_story"

        app._custom_story_draft = CustomStoryDraft(
            title="雾港最后一班船",
            subtitle="玩家自定义卷宗",
            location="海港候船厅",
            setting="深夜浓雾封港，候船厅里只剩值班员、旅客和延误广播。",
            core_case="船务公司的负责人被发现死在封闭的候船通道内，所有人都说自己没有离开大厅。",
            opening_hook="最后一班船取消后，广播突然中断，整个候船厅陷入一阵短暂的漆黑。",
            victim_name="闻野",
            victim_identity="船务公司负责人",
            detective_identity="负责复盘雾港案件的侦探",
        )

        app._save_custom_story()

        assert app._mode == "story_browser"
        assert len(app._stories) == 2
        assert app.current_story.title == "雾港最后一班船"
        assert any((tmp_path / story.id / "story.json").exists() for story in app._stories if story.title == "雾港最后一班船")
    finally:
        pygame.quit()
