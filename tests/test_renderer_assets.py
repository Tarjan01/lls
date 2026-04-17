from __future__ import annotations

from pathlib import Path

import pygame
import pytest

from reverse_detective.ai_client import build_default_premise
from reverse_detective.game_state import GameSessionState
from reverse_detective.renderer import Renderer
from reverse_detective.scene_loader import load_scene_payload
from reverse_detective.utils.assets import ensure_asset_parent, resolve_cached_asset_path


def _write_asset_image(path: Path, color: tuple[int, int, int], size: tuple[int, int]) -> None:
    surface = pygame.Surface(size, pygame.SRCALPHA)
    surface.fill(color)
    ensure_asset_parent(path)
    pygame.image.save(surface, str(path))


def test_renderer_draws_cached_assets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))

    background_path = resolve_cached_asset_path("background", "bg_demo_room.png", tmp_path)
    npc_path = resolve_cached_asset_path("npc", "npc_detective_demo.png", tmp_path)
    interactable_path = resolve_cached_asset_path(
        "interactable",
        "item_letter_demo.png",
        tmp_path,
    )
    assert background_path is not None
    assert npc_path is not None
    assert interactable_path is not None

    _write_asset_image(background_path, (12, 180, 44), (48, 48))
    _write_asset_image(npc_path, (220, 36, 52), (48, 48))
    _write_asset_image(interactable_path, (38, 84, 220), (48, 48))

    screen = pygame.display.get_surface()
    assert screen is not None

    renderer = Renderer(screen, 1280, 720, 520, asset_root=tmp_path)
    scene = load_scene_payload(
        {
            "scene": {
                "background_image": "bg_demo_room.png",
                "bgm": "silent.mp3",
                "description": "演示场景",
            },
            "npcs": [
                {
                    "id": "detective",
                    "name": "侦探",
                    "image": "npc_detective_demo.png",
                    "position": [640, 320],
                    "patrol": None,
                }
            ],
            "interactables": [
                {
                    "id": "letter",
                    "name": "信件",
                    "image": "item_letter_demo.png",
                    "position": [300, 400],
                    "options": [
                        {
                            "label": "查看",
                            "action_id": "inspect",
                            "resolution_mode": "local_rule",
                            "local_logic": {
                                "requires_state": {},
                                "set_state": {},
                                "success_text": "你查看了信件封口，确认它仍保持着未被拆开的假象。",
                                "failure_text": "你再次查看信件，也没有额外变化。",
                            },
                        }
                    ],
                }
            ],
            "narrative": "场景素材应当替代纯色占位块。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    session = GameSessionState.create(build_default_premise())
    session.finish_initial_scene(scene)
    session.set_player_position(140, 480)

    try:
        renderer.draw(session, "Live API", 0.0, "玩家", "演示卷宗")

        background_pixel = screen.get_at((24, 24))[:3]
        assert background_pixel[1] > 150
        assert background_pixel[1] > background_pixel[0]
        assert background_pixel[1] > background_pixel[2]
        assert screen.get_at((640, 320))[:3] == (220, 36, 52)
        assert screen.get_at((300, 400))[:3] == (38, 84, 220)
    finally:
        pygame.quit()


def test_renderer_draws_loading_overlay_with_text_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    renderer = Renderer(screen, 1280, 720, 520, asset_root=tmp_path)
    scene = load_scene_payload(
        {
            "scene": {
                "background_image": "bg.png",
                "bgm": "silent.mp3",
                "description": "加载中的场景",
            },
            "npcs": [],
            "interactables": [],
            "narrative": "当前是等待 AI 返回的阶段。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    session = GameSessionState.create(build_default_premise())
    session.finish_initial_scene(scene)
    session.record_system_text("系统提示", "这里应该显示之前的文本。")
    session.loading = True

    try:
        renderer.draw(session, "Live API", 1.2, "玩家", "演示卷宗")
        pixel = screen.get_at((640, 220))[:3]
        assert any(channel > 0 for channel in pixel)
    finally:
        pygame.quit()


def test_renderer_resolves_patrol_as_closed_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    renderer = Renderer(screen, 1280, 720, 520, asset_root=tmp_path)
    scene = load_scene_payload(
        {
            "scene": {
                "background_image": "bg.png",
                "bgm": "silent.mp3",
                "description": "巡逻闭环测试",
            },
            "npcs": [
                {
                    "id": "guard",
                    "name": "守卫",
                    "image": "npc.png",
                    "position": [100, 100],
                    "patrol": [[200, 100], [200, 200], [100, 200]],
                }
            ],
            "interactables": [],
            "narrative": "守卫应沿闭环路线巡逻。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    try:
        position = renderer._resolve_npc_position(scene.npcs[0], 350.0 / 78.0)
        assert position == (100, 150)
    finally:
        pygame.quit()
