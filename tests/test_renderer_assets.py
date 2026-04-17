from __future__ import annotations

from pathlib import Path

import pygame
import pytest

from reverse_detective.ai_client import build_default_premise
from reverse_detective.game_state import GameSessionState
from reverse_detective.models import NPC
from reverse_detective.renderer import MenuRenderer, Renderer
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


def test_menu_renderer_prefers_cybernoir_loft_background(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    loft_path = resolve_cached_asset_path("background", "cybernoir_loft_lounge.png", tmp_path)
    cover_path = resolve_cached_asset_path("background", "menu_cybernoir_cover_3.png", tmp_path)
    assert loft_path is not None
    assert cover_path is not None

    _write_asset_image(loft_path, (180, 30, 40), (48, 48))
    _write_asset_image(cover_path, (20, 120, 220), (48, 48))

    renderer = MenuRenderer(screen, 1280, 720, asset_root=tmp_path)

    try:
        surface = renderer._load_menu_background_surface("main_menu", (48, 48))
        assert surface is not None
        assert surface.get_at((12, 12))[:3] == (180, 30, 40)
    finally:
        pygame.quit()


def test_menu_renderer_uses_gendered_character_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    female_path = tmp_path / "character" / "1.png"
    male_path = tmp_path / "character" / "2.png"
    _write_asset_image(female_path, (220, 44, 72), (64, 64))
    _write_asset_image(male_path, (44, 118, 228), (64, 64))

    renderer = MenuRenderer(screen, 1280, 720, asset_root=tmp_path)

    try:
        female_surface = renderer._load_menu_portrait_surface("female", (48, 48), "player")
        male_surface = renderer._load_menu_portrait_surface("male", (48, 48), "player")

        assert female_surface is not None
        assert male_surface is not None
        female_pixel = female_surface.get_at((12, 12))[:3]
        male_pixel = male_surface.get_at((12, 12))[:3]
        assert female_pixel[0] > 180
        assert female_pixel[0] > female_pixel[1]
        assert female_pixel[0] > female_pixel[2]
        assert male_pixel[2] > 180
        assert male_pixel[2] > male_pixel[0]
        assert male_pixel[2] > male_pixel[1]
    finally:
        pygame.quit()


def test_menu_renderer_reserves_left_strip_for_player_showcase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    renderer = MenuRenderer(screen, 1280, 720)

    try:
        showcase_rect = renderer._menu_player_showcase_rect()
        content_rect = renderer._menu_content_rect()

        assert content_rect.left > showcase_rect.right
        assert showcase_rect.left == 24
        assert showcase_rect.width >= 160
    finally:
        pygame.quit()


def test_renderer_prefers_character_assets_for_player(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    _write_asset_image(tmp_path / "character" / "1.png", (220, 44, 72), (64, 64))
    _write_asset_image(tmp_path / "character" / "2.png", (44, 118, 228), (64, 64))
    _write_asset_image(tmp_path / "npcs" / "menu_player_female.png", (22, 200, 110), (64, 64))
    _write_asset_image(tmp_path / "npcs" / "menu_player_male.png", (210, 180, 18), (64, 64))

    renderer = Renderer(screen, 1280, 720, 520, asset_root=tmp_path)

    try:
        female_surface = renderer._load_player_surface("female", (48, 48), "player")
        male_surface = renderer._load_player_surface("male", (48, 48), "player")

        assert female_surface is not None
        assert male_surface is not None
        female_pixel = female_surface.get_at((12, 12))[:3]
        male_pixel = male_surface.get_at((12, 12))[:3]
        assert female_pixel[0] > female_pixel[1]
        assert female_pixel[0] > female_pixel[2]
        assert male_pixel[2] > male_pixel[0]
        assert male_pixel[2] > male_pixel[1]
    finally:
        pygame.quit()


def test_renderer_prefers_character_assets_for_npcs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    _write_asset_image(tmp_path / "character" / "4.png", (228, 92, 156), (64, 64))
    _write_asset_image(tmp_path / "character" / "5.png", (236, 236, 236), (64, 64))
    _write_asset_image(tmp_path / "npcs" / "npc.png", (24, 80, 200), (64, 64))

    renderer = Renderer(screen, 1280, 720, 520, asset_root=tmp_path)
    doctor = NPC(id="doctor_zhang", name="张博士", image="npc.png", position=(100, 100), patrol=None)
    female = NPC(id="su_man", name="苏曼", image="npc.png", position=(100, 100), patrol=None)

    try:
        doctor_surface = renderer._load_npc_surface(doctor, (48, 48))
        female_surface = renderer._load_npc_surface(female, (48, 48))

        assert doctor_surface is not None
        assert female_surface is not None
        doctor_pixel = doctor_surface.get_at((12, 12))[:3]
        female_pixel = female_surface.get_at((12, 12))[:3]
        assert min(doctor_pixel) > 180
        assert female_pixel[0] > 180
        assert female_pixel[2] > 120
    finally:
        pygame.quit()


def test_renderer_places_freeform_action_trigger_left_of_sidebar(
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
                "description": "自由行动入口布局测试",
            },
            "npcs": [],
            "interactables": [],
            "narrative": "用于确认自由行动按钮不会再压在右侧栏卡片上。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    session = GameSessionState.create(build_default_premise())
    session.finish_initial_scene(scene)

    try:
        renderer.draw(session, "Live API", 0.0, "玩家", "演示卷宗")

        freeform_target = next(
            target for target in renderer._action_targets if target.action == "open_freeform_action"
        )
        action_rect = freeform_target.rect
        sidebar_left = renderer._width - 266

        assert renderer.consume_action_click(action_rect.center) == "open_freeform_action"
        assert action_rect.right < sidebar_left
    finally:
        pygame.quit()
