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


def _opaque_pixel_count(surface: pygame.Surface, y: int) -> int:
    return sum(1 for x in range(surface.get_width()) if surface.get_at((x, y))[3] > 0)


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
                "description": "婕旂ず鍦烘櫙",
            },
            "npcs": [
                {
                    "id": "detective",
                    "name": "渚︽帰",
                    "image": "npc_detective_demo.png",
                    "position": [640, 320],
                    "patrol": None,
                }
            ],
            "interactables": [
                {
                    "id": "letter",
                    "name": "淇′欢",
                    "image": "item_letter_demo.png",
                    "position": [300, 400],
                    "options": [
                        {
                            "label": "鏌ョ湅",
                            "action_id": "inspect",
                            "resolution_mode": "local_rule",
                            "local_logic": {
                                "requires_state": {},
                                "set_state": {},
                                "success_text": "You checked the letter seal and confirmed it was still unopened.",
                                "failure_text": "You checked the letter again, but nothing had changed.",
                            },
                        }
                    ],
                }
            ],
            "narrative": "Scene art should replace the plain placeholder block.",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    session = GameSessionState.create(build_default_premise())
    session.finish_initial_scene(scene)
    session.set_player_position(140, 480)

    try:
        renderer.draw(session, "Live API", 0.0, "鐜╁", "婕旂ず鍗峰畻")

        background_pixel = screen.get_at((24, 120))[:3]
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
                "description": "鍔犺浇涓殑鍦烘櫙",
            },
            "npcs": [],
            "interactables": [],
            "narrative": "The scene should render while waiting for AI to return.",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    session = GameSessionState.create(build_default_premise())
    session.finish_initial_scene(scene)
    session.record_system_text("system note", "This text should appear before the current message.")
    session.loading = True

    try:
        renderer.draw(session, "Live API", 1.2, "鐜╁", "婕旂ず鍗峰畻")
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
                "description": "Patrol loop test while loading assets.",
            },
            "npcs": [
                {
                    "id": "guard",
                    "name": "瀹堝崼",
                    "image": "npc.png",
                    "position": [100, 100],
                    "patrol": [[200, 100], [200, 200], [100, 200]],
                }
            ],
            "interactables": [],
            "narrative": "Guard patrol path loop test.",
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


def test_renderer_preserves_character_aspect_ratio_when_scaling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    _write_asset_image(tmp_path / "character" / "2.png", (44, 118, 228), (20, 80))
    renderer = Renderer(screen, 1280, 720, 520, asset_root=tmp_path)

    try:
        surface = renderer._load_player_surface("male", (48, 48), "player")
        assert surface is not None
        assert surface.get_at((2, 24))[3] == 0
        assert _opaque_pixel_count(surface, 24) >= 14
        center_pixel = surface.get_at((24, 24))[:3]
        assert center_pixel[2] > center_pixel[0]
        assert center_pixel[2] > center_pixel[1]
    finally:
        pygame.quit()


def test_menu_renderer_preserves_character_aspect_ratio_when_scaling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    _write_asset_image(tmp_path / "character" / "1.png", (220, 44, 72), (20, 80))
    renderer = MenuRenderer(screen, 1280, 720, asset_root=tmp_path)

    try:
        surface = renderer._load_menu_portrait_surface("female", (48, 48), "player")
        assert surface is not None
        assert surface.get_at((2, 24))[3] == 0
        assert _opaque_pixel_count(surface, 24) >= 14
        center_pixel = surface.get_at((24, 24))[:3]
        assert center_pixel[0] > center_pixel[1]
        assert center_pixel[0] > center_pixel[2]
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
    doctor = NPC(id="doctor_zhang", name="张医生", image="npc.png", position=(100, 100), patrol=None)
    female = NPC(id="su_man", name="鑻忔浖", image="npc.png", position=(100, 100), patrol=None)

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


def test_renderer_stabilizes_story_character_mappings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    _write_asset_image(tmp_path / "character" / "3.png", (188, 62, 42), (64, 64))
    _write_asset_image(tmp_path / "character" / "4.png", (226, 74, 174), (64, 64))
    _write_asset_image(tmp_path / "character" / "5.png", (232, 232, 232), (64, 64))
    _write_asset_image(tmp_path / "character" / "6.png", (44, 120, 220), (64, 64))
    _write_asset_image(tmp_path / "npcs" / "npc.png", (18, 180, 88), (64, 64))

    renderer = Renderer(screen, 1280, 720, 520, asset_root=tmp_path)
    old_man = NPC(id="old_chen", name="鑰侀檲", image="npc.png", position=(100, 100), patrol=None)
    security = NPC(id="detective", name="鍛ㄥ惎", image="npc.png", position=(100, 100), patrol=None)
    woman = NPC(id="auction_rival", name="阮知夏", image="npc.png", position=(100, 100), patrol=None)
    doctor = NPC(id="private_doctor", name="何医生", image="npc.png", position=(100, 100), patrol=None)

    try:
        old_surface = renderer._load_npc_surface(old_man, (48, 48))
        security_surface = renderer._load_npc_surface(security, (48, 48))
        woman_surface = renderer._load_npc_surface(woman, (48, 48))
        doctor_surface = renderer._load_npc_surface(doctor, (48, 48))

        assert old_surface is not None
        assert security_surface is not None
        assert woman_surface is not None
        assert doctor_surface is not None

        old_pixel = old_surface.get_at((12, 12))[:3]
        security_pixel = security_surface.get_at((12, 12))[:3]
        woman_pixel = woman_surface.get_at((12, 12))[:3]
        doctor_pixel = doctor_surface.get_at((12, 12))[:3]

        assert old_pixel[0] > old_pixel[2]
        assert security_pixel[2] > security_pixel[0]
        assert woman_pixel[0] > 180
        assert woman_pixel[2] > 120
        assert min(doctor_pixel) > 180
    finally:
        pygame.quit()


def test_renderer_places_action_slot_in_bottom_panel(
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
                "description": "底部动作槽布局测试",
            },
            "npcs": [],
            "interactables": [
                {
                    "id": "case_file",
                    "name": "案卷",
                    "image": "case_file.png",
                    "position": [580, 280],
                    "state": {
                        "opened": False,
                        "locked": False,
                        "hidden": False,
                        "disabled": False,
                    },
                    "options": [
                        {
                            "label": "检查案卷",
                            "action_id": "inspect_file",
                            "resolution_mode": "local_rule",
                            "local_logic": {
                                "requires_state": {"opened": False},
                                "set_state": {"opened": True},
                                "success_text": "你翻看了案卷。",
                                "failure_text": "案卷已经翻看过了。",
                            },
                        }
                    ],
                }
            ],
            "narrative": "用于确认底部动作槽会进入下方交互区。",
            "game_status": "ongoing",
            "ending_text": None,
        }
    )

    session = GameSessionState.create(build_default_premise())
    session.finish_initial_scene(scene)
    session.set_active_interactable("case_file")

    try:
        renderer.draw(session, "Live API", 0.0, "玩家", "演示卷宗")

        action_target = next(
            target for target in renderer._action_targets if target.action == "choose_option:0"
        )

        assert action_target.rect.top >= renderer._height - 176
        assert renderer.consume_action_click(action_target.rect.center) == "choose_option:0"
    finally:
        pygame.quit()
