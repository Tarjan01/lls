from __future__ import annotations

import math
from pathlib import Path

import pygame


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = PROJECT_ROOT / ".tmp_assets"
ASSET_ROOT = PROJECT_ROOT / "assets" / "img"

BACKGROUND_SIZE = (1280, 520)
ICON_SIZE = (256, 256)


def main() -> None:
    pygame.init()
    try:
        build_npc_assets()
        build_interactable_assets()
        build_background_assets()
    finally:
        pygame.quit()


def build_npc_assets() -> None:
    male_person_idle = load_image(
        TMP_ROOT
        / "toon-characters"
        / "Male person"
        / "PNG"
        / "Poses HD"
        / "character_malePerson_idle.png"
    )
    male_person_think = load_image(
        TMP_ROOT
        / "toon-characters"
        / "Male person"
        / "PNG"
        / "Poses HD"
        / "character_malePerson_think.png"
    )
    male_person_show = load_image(
        TMP_ROOT
        / "toon-characters"
        / "Male person"
        / "PNG"
        / "Poses HD"
        / "character_malePerson_show.png"
    )
    male_adventurer_talk = load_image(
        TMP_ROOT
        / "toon-characters"
        / "Male adventurer"
        / "PNG"
        / "Poses HD"
        / "character_maleAdventurer_talk.png"
    )
    male_adventurer_hold = load_image(
        TMP_ROOT
        / "toon-characters"
        / "Male adventurer"
        / "PNG"
        / "Poses HD"
        / "character_maleAdventurer_hold.png"
    )
    female_person_talk = load_image(
        TMP_ROOT
        / "toon-characters"
        / "Female person"
        / "PNG"
        / "Poses HD"
        / "character_femalePerson_talk.png"
    )
    female_person_hold = load_image(
        TMP_ROOT
        / "toon-characters"
        / "Female person"
        / "PNG"
        / "Poses HD"
        / "character_femalePerson_hold.png"
    )
    female_adventurer_think = load_image(
        TMP_ROOT
        / "toon-characters"
        / "Female adventurer"
        / "PNG"
        / "Poses HD"
        / "character_femaleAdventurer_think.png"
    )
    robot_idle = load_image(
        TMP_ROOT
        / "toon-characters"
        / "Robot"
        / "PNG"
        / "Poses HD"
        / "character_robot_idle.png"
    )
    zombie_idle = load_image(
        TMP_ROOT
        / "toon-characters"
        / "Zombie"
        / "PNG"
        / "Poses HD"
        / "character_zombie_idle.png"
    )

    npc_groups = [
        (male_person_think, ["hitman_suit.png", "detective.png"]),
        (male_person_idle, ["man_blue.png", "victim.png"]),
        (male_adventurer_talk, ["man_brown.png", "witness.png"]),
        (male_person_show, ["man_old.png", "private_doctor.png"]),
        (female_adventurer_think, ["woman_green.png", "female_suspect.png"]),
        (female_person_hold, ["survivor.png", "assistant.png"]),
        (male_adventurer_hold, ["security_soldier.png", "security_guard.png"]),
        (robot_idle, ["robot_assistant.png", "technician.png"]),
        (zombie_idle, ["gaunt_figure.png", "victim_body.png"]),
    ]

    for sprite, names in npc_groups:
        canvas = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
        scaled = fit_to_box(sprite, 182, 224)
        rect = scaled.get_rect(midbottom=(ICON_SIZE[0] // 2, ICON_SIZE[1] - 10))
        canvas.blit(scaled, rect)
        for name in names:
            save_surface(canvas, ASSET_ROOT / "npcs" / name)


def build_interactable_assets() -> None:
    box = fit_to_box(
        load_image(TMP_ROOT / "platformer-art-deluxe" / "Base pack" / "Tiles" / "box.png"),
        162,
        162,
    )
    clock = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "clock.png"
        ),
        150,
        150,
    )
    window_low = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "windowLowLeadlight.png"
        ),
        138,
        114,
    )
    door_top = fit_to_box(
        load_image(
            TMP_ROOT / "platformer-art-deluxe" / "Base pack" / "Tiles" / "door_closedTop.png"
        ),
        122,
        62,
    )
    door_mid = fit_to_box(
        load_image(
            TMP_ROOT / "platformer-art-deluxe" / "Base pack" / "Tiles" / "door_closedMid.png"
        ),
        122,
        138,
    )
    open_door_top = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "doorOpenTop.png"
        ),
        132,
        68,
    )
    open_door_mid = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "doorOpen.png"
        ),
        132,
        146,
    )

    save_surface(make_folder_icon((92, 145, 188), "卷"), ASSET_ROOT / "interactables" / "case_file.png")
    save_surface(make_folder_icon((124, 91, 58), "簿"), ASSET_ROOT / "interactables" / "guest_register.png")
    save_surface(make_console_icon(), ASSET_ROOT / "interactables" / "control_console.png")
    save_surface(make_crate_icon(box), ASSET_ROOT / "interactables" / "evidence_crate.png")
    save_surface(make_bag_icon((83, 126, 161), tag="野"), ASSET_ROOT / "interactables" / "field_bag.png")
    save_surface(make_bag_icon((153, 101, 91), tag="手"), ASSET_ROOT / "interactables" / "small_bag.png")
    save_surface(make_bag_icon((121, 88, 52), tag="工"), ASSET_ROOT / "interactables" / "tool_bag.png")
    save_surface(make_bag_icon((121, 88, 52), tag="工"), ASSET_ROOT / "interactables" / "tool_case.png")
    save_surface(make_bag_icon((136, 72, 72), tag="+"), ASSET_ROOT / "interactables" / "medical_bag.png")
    save_surface(make_bag_icon((136, 72, 72), tag="+"), ASSET_ROOT / "interactables" / "support_kit.png")
    save_surface(make_blade_icon(), ASSET_ROOT / "interactables" / "knife_tool.png")
    save_surface(make_gun_icon(), ASSET_ROOT / "interactables" / "handgun_tool.png")
    save_surface(make_pen_device_icon(), ASSET_ROOT / "interactables" / "silencer_tool.png")
    save_surface(make_jammer_icon(), ASSET_ROOT / "interactables" / "signal_jammer.png")
    save_surface(make_rig_icon(), ASSET_ROOT / "interactables" / "signal_rig.png")
    save_surface(make_round_table_icon(), ASSET_ROOT / "interactables" / "round_table.png")
    save_surface(make_clock_icon(clock), ASSET_ROOT / "interactables" / "corridor_watch.png")
    save_surface(make_window_icon(window_low), ASSET_ROOT / "interactables" / "window_panel.png")
    save_surface(make_window_icon(window_low), ASSET_ROOT / "interactables" / "window.png")
    save_surface(make_locked_door_icon(door_top, door_mid), ASSET_ROOT / "interactables" / "locked_door.png")
    open_door_icon = make_open_door_icon(open_door_top, open_door_mid)
    save_surface(open_door_icon, ASSET_ROOT / "interactables" / "open_door.png")
    save_surface(open_door_icon, ASSET_ROOT / "interactables" / "service_passage.png")


def build_background_assets() -> None:
    tree = fit_to_box(load_image(TMP_ROOT / "background-elements" / "PNG" / "tree10.png"), 180, 220)
    tree_alt = fit_to_box(load_image(TMP_ROOT / "background-elements" / "PNG" / "tree07.png"), 180, 220)
    hill = fit_to_box(load_image(TMP_ROOT / "background-elements" / "PNG" / "Flat" / "hills1.png"), 1280, 220)
    house_front = fit_to_box(
        load_image(TMP_ROOT / "background-elements" / "PNG" / "house_beige_front.png"),
        196,
        224,
    )
    house_side = fit_to_box(
        load_image(TMP_ROOT / "background-elements" / "PNG" / "house_beige_side.png"),
        268,
        224,
    )
    awning = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "awningGreenRed.png"
        ),
        180,
        54,
    )
    window_low = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "windowLowLeadlight.png"
        ),
        90,
        78,
    )
    window_tall_top = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "windowHighLeadlightTop.png"
        ),
        78,
        42,
    )
    window_tall_mid = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "windowHighLeadlightMid.png"
        ),
        78,
        82,
    )
    window_tall_bottom = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "windowHighLeadlightBottom.png"
        ),
        78,
        42,
    )
    door_top = fit_to_box(
        load_image(
            TMP_ROOT / "platformer-art-deluxe" / "Base pack" / "Tiles" / "door_closedTop.png"
        ),
        112,
        58,
    )
    door_mid = fit_to_box(
        load_image(
            TMP_ROOT / "platformer-art-deluxe" / "Base pack" / "Tiles" / "door_closedMid.png"
        ),
        112,
        126,
    )
    open_door_top = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "doorOpenTop.png"
        ),
        116,
        62,
    )
    open_door_mid = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "doorOpen.png"
        ),
        116,
        132,
    )
    clock = fit_to_box(
        load_image(
            TMP_ROOT
            / "platformer-art-deluxe"
            / "Buildings expansion"
            / "Tiles"
            / "clock.png"
        ),
        64,
        64,
    )

    save_surface(
        make_hall_background(
            wall_top=(23, 39, 66),
            wall_bottom=(54, 72, 105),
            floor=(68, 52, 48),
            accent=(214, 201, 166),
            door_assets=(door_top, door_mid),
            window_assets=(window_tall_top, window_tall_mid, window_tall_bottom),
            mood="rain",
        ),
        ASSET_ROOT / "backgrounds" / "rainy_villa_hall.png",
    )
    save_surface(
        make_hall_background(
            wall_top=(36, 44, 58),
            wall_bottom=(66, 74, 94),
            floor=(54, 45, 52),
            accent=(203, 198, 182),
            door_assets=(open_door_top, open_door_mid),
            window_assets=(window_tall_top, window_tall_mid, window_tall_bottom),
            mood="ending",
        ),
        ASSET_ROOT / "backgrounds" / "rainy_villa_ending.png",
    )
    save_surface(
        make_study_background(door_top, door_mid, window_tall_top, window_tall_mid, window_tall_bottom),
        ASSET_ROOT / "backgrounds" / "mansion_study_room.png",
    )
    save_surface(
        make_gallery_background(door_top, door_mid, window_tall_top, window_tall_mid, window_tall_bottom, brighter=True),
        ASSET_ROOT / "backgrounds" / "gallery_inner_hall.png",
    )
    save_surface(
        make_gallery_background(door_top, door_mid, window_tall_top, window_tall_mid, window_tall_bottom, brighter=False),
        ASSET_ROOT / "backgrounds" / "front_gallery.png",
    )
    save_surface(
        make_control_room_background(door_top, door_mid, clock),
        ASSET_ROOT / "backgrounds" / "security_control_room.png",
    )
    save_surface(
        make_control_room_background(open_door_top, open_door_mid, clock, warmer=True),
        ASSET_ROOT / "backgrounds" / "gallery_surveillance_room.png",
    )
    save_surface(
        make_exterior_background(hill, house_front, house_side, awning, tree, tree_alt, night=True),
        ASSET_ROOT / "backgrounds" / "villa_exterior.png",
    )
    save_surface(
        make_exterior_background(hill, house_front, house_side, awning, tree, tree_alt, night=False),
        ASSET_ROOT / "backgrounds" / "estate_garden.png",
    )
    save_surface(
        make_forest_background(hill, tree, tree_alt),
        ASSET_ROOT / "backgrounds" / "forest_edge.png",
    )
    save_surface(
        make_road_background(hill, tree, house_front, window_low),
        ASSET_ROOT / "backgrounds" / "mountain_road.png",
    )


def make_hall_background(
    *,
    wall_top: tuple[int, int, int],
    wall_bottom: tuple[int, int, int],
    floor: tuple[int, int, int],
    accent: tuple[int, int, int],
    door_assets: tuple[pygame.Surface, pygame.Surface],
    window_assets: tuple[pygame.Surface, pygame.Surface, pygame.Surface],
    mood: str,
) -> pygame.Surface:
    surface = pygame.Surface(BACKGROUND_SIZE, pygame.SRCALPHA)
    gradient_fill(surface, pygame.Rect(0, 0, 1280, 360), wall_top, wall_bottom)
    gradient_fill(surface, pygame.Rect(0, 360, 1280, 160), shift_color(floor, 24), floor)
    pygame.draw.rect(surface, shift_color(accent, -18), pygame.Rect(0, 318, 1280, 10))
    for x in range(0, 1281, 160):
        pygame.draw.line(surface, shift_color(wall_bottom, 16), (x, 0), (x, 360), 3)
    for x in (180, 360, 920, 1100):
        draw_tall_window(surface, (x, 118), window_assets)
    draw_door(surface, (604, 182), door_assets)
    pygame.draw.rect(surface, shift_color(accent, -36), pygame.Rect(96, 210, 184, 118), border_radius=18)
    pygame.draw.rect(surface, shift_color(accent, -14), pygame.Rect(142, 234, 92, 72), border_radius=12)
    pygame.draw.rect(surface, shift_color(accent, -48), pygame.Rect(970, 214, 192, 110), border_radius=18)
    pygame.draw.rect(surface, shift_color(accent, -8), pygame.Rect(1020, 236, 92, 60), border_radius=12)
    if mood == "rain":
        for offset in range(0, 1280, 48):
            pygame.draw.line(surface, (180, 206, 232, 52), (offset, 28), (offset - 54, 188), 2)
    else:
        vignette_overlay(surface, (44, 18, 20, 62))
        pygame.draw.rect(surface, (173, 81, 74), pygame.Rect(0, 350, 1280, 6))
    return surface


def make_study_background(
    door_top: pygame.Surface,
    door_mid: pygame.Surface,
    window_tall_top: pygame.Surface,
    window_tall_mid: pygame.Surface,
    window_tall_bottom: pygame.Surface,
) -> pygame.Surface:
    surface = pygame.Surface(BACKGROUND_SIZE, pygame.SRCALPHA)
    gradient_fill(surface, pygame.Rect(0, 0, 1280, 360), (57, 47, 42), (101, 84, 68))
    gradient_fill(surface, pygame.Rect(0, 360, 1280, 160), (92, 64, 44), (66, 46, 36))
    pygame.draw.rect(surface, (135, 116, 90), pygame.Rect(0, 300, 1280, 18))
    for x in (168, 322, 476, 804, 958, 1112):
        draw_tall_window(surface, (x, 116), (window_tall_top, window_tall_mid, window_tall_bottom))
    draw_door(surface, (580, 176), (door_top, door_mid))
    for x in (88, 1180):
        pygame.draw.rect(surface, (77, 49, 36), pygame.Rect(x, 126, 40, 192), border_radius=8)
    for shelf_x in (92, 1180):
        for level in range(3):
            pygame.draw.rect(
                surface,
                (148, 128, 97),
                pygame.Rect(shelf_x - 6, 154 + level * 52, 52, 8),
                border_radius=4,
            )
    pygame.draw.rect(surface, (58, 43, 34), pygame.Rect(340, 388, 600, 22), border_radius=11)
    pygame.draw.rect(surface, (140, 108, 78), pygame.Rect(400, 368, 480, 20), border_radius=10)
    for x in (450, 620, 790):
        pygame.draw.rect(surface, (121, 86, 60), pygame.Rect(x, 408, 18, 74), border_radius=6)
    return surface


def make_gallery_background(
    door_top: pygame.Surface,
    door_mid: pygame.Surface,
    window_tall_top: pygame.Surface,
    window_tall_mid: pygame.Surface,
    window_tall_bottom: pygame.Surface,
    *,
    brighter: bool,
) -> pygame.Surface:
    surface = pygame.Surface(BACKGROUND_SIZE, pygame.SRCALPHA)
    if brighter:
        top, bottom, floor = (233, 229, 217), (214, 205, 188), (186, 172, 146)
    else:
        top, bottom, floor = (194, 186, 170), (150, 138, 125), (97, 90, 87)
    gradient_fill(surface, pygame.Rect(0, 0, 1280, 360), top, bottom)
    gradient_fill(surface, pygame.Rect(0, 360, 1280, 160), shift_color(floor, 18), floor)
    pygame.draw.rect(surface, shift_color(bottom, -36), pygame.Rect(0, 316, 1280, 10))
    for x in (204, 434, 662, 890, 1118):
        draw_tall_window(surface, (x, 92), (window_tall_top, window_tall_mid, window_tall_bottom))
    draw_door(surface, (604, 182), (door_top, door_mid))
    for pedestal_x in (210, 426, 858, 1074):
        pygame.draw.rect(surface, shift_color(floor, -32), pygame.Rect(pedestal_x, 330, 44, 80), border_radius=8)
        pygame.draw.rect(surface, shift_color(floor, -4), pygame.Rect(pedestal_x - 10, 402, 64, 12), border_radius=6)
        pygame.draw.circle(surface, shift_color(top, -56), (pedestal_x + 22, 312), 20)
    if not brighter:
        vignette_overlay(surface, (19, 16, 24, 44))
    return surface


def make_control_room_background(
    door_top: pygame.Surface,
    door_mid: pygame.Surface,
    clock: pygame.Surface,
    *,
    warmer: bool = False,
) -> pygame.Surface:
    surface = pygame.Surface(BACKGROUND_SIZE, pygame.SRCALPHA)
    if warmer:
        wall_top, wall_bottom, floor = (54, 54, 63), (88, 79, 81), (63, 50, 53)
        screen_color = (97, 186, 180)
    else:
        wall_top, wall_bottom, floor = (20, 27, 39), (39, 52, 70), (31, 34, 42)
        screen_color = (90, 213, 206)
    gradient_fill(surface, pygame.Rect(0, 0, 1280, 360), wall_top, wall_bottom)
    gradient_fill(surface, pygame.Rect(0, 360, 1280, 160), shift_color(floor, 18), floor)
    draw_door(surface, (86, 176), (door_top, door_mid))
    draw_door(surface, (1080, 176), (door_top, door_mid))
    for column_x in (240, 410, 580, 750, 920):
        frame = pygame.Rect(column_x, 102, 126, 88)
        pygame.draw.rect(surface, (16, 20, 26), frame, border_radius=14)
        pygame.draw.rect(surface, shift_color(screen_color, -46), frame, width=3, border_radius=14)
        glow = pygame.Surface((frame.width, frame.height), pygame.SRCALPHA)
        glow.fill((*screen_color, 42))
        surface.blit(glow, frame)
        for line in range(4):
            pygame.draw.rect(
                surface,
                shift_color(screen_color, 12),
                pygame.Rect(frame.x + 14, frame.y + 14 + line * 16, frame.width - 28, 6),
                border_radius=3,
            )
    pygame.draw.rect(surface, (42, 47, 58), pygame.Rect(230, 292, 820, 34), border_radius=16)
    pygame.draw.rect(surface, (77, 84, 96), pygame.Rect(214, 322, 852, 16), border_radius=8)
    for x in (286, 520, 754, 988):
        pygame.draw.rect(surface, (66, 73, 85), pygame.Rect(x, 332, 22, 74), border_radius=8)
    surface.blit(clock, clock.get_rect(center=(640, 74)))
    return surface


def make_exterior_background(
    hill: pygame.Surface,
    house_front: pygame.Surface,
    house_side: pygame.Surface,
    awning: pygame.Surface,
    tree: pygame.Surface,
    tree_alt: pygame.Surface,
    *,
    night: bool,
) -> pygame.Surface:
    surface = pygame.Surface(BACKGROUND_SIZE, pygame.SRCALPHA)
    if night:
        gradient_fill(surface, pygame.Rect(0, 0, 1280, 520), (27, 36, 58), (90, 97, 130))
    else:
        gradient_fill(surface, pygame.Rect(0, 0, 1280, 520), (180, 220, 236), (225, 244, 232))
    surface.blit(hill, hill.get_rect(midbottom=(640, 340)))
    ground = pygame.Rect(0, 344, 1280, 176)
    gradient_fill(surface, ground, (127, 164, 95), (96, 133, 77))
    villa_rect = house_side.get_rect(midbottom=(704, 344))
    surface.blit(house_side, villa_rect)
    front_left = house_front.get_rect(midbottom=(564, 350))
    front_right = house_front.get_rect(midbottom=(826, 350))
    surface.blit(house_front, front_left)
    surface.blit(house_front, front_right)
    surface.blit(awning, awning.get_rect(midbottom=(564, 332)))
    surface.blit(awning, awning.get_rect(midbottom=(826, 332)))
    for pos in ((184, 350), (284, 350), (1012, 350), (1122, 350)):
        sprite = tree if pos[0] < 600 else tree_alt
        surface.blit(sprite, sprite.get_rect(midbottom=pos))
    if night:
        vignette_overlay(surface, (10, 13, 20, 38))
    return surface


def make_forest_background(
    hill: pygame.Surface,
    tree: pygame.Surface,
    tree_alt: pygame.Surface,
) -> pygame.Surface:
    surface = pygame.Surface(BACKGROUND_SIZE, pygame.SRCALPHA)
    gradient_fill(surface, pygame.Rect(0, 0, 1280, 520), (132, 186, 207), (208, 234, 214))
    surface.blit(hill, hill.get_rect(midbottom=(640, 300)))
    surface.blit(fit_to_box(hill, 1400, 180), hill.get_rect(midbottom=(640, 350)))
    gradient_fill(surface, pygame.Rect(0, 340, 1280, 180), (122, 152, 92), (92, 123, 71))
    for x in (100, 220, 360, 510, 760, 930, 1090, 1210):
        sprite = tree if x % 2 == 0 else tree_alt
        surface.blit(sprite, sprite.get_rect(midbottom=(x, 376 if x < 700 else 392)))
    pygame.draw.rect(surface, (132, 119, 96), pygame.Rect(0, 420, 1280, 100))
    pygame.draw.rect(surface, (116, 102, 82), pygame.Rect(0, 412, 1280, 14))
    return surface


def make_road_background(
    hill: pygame.Surface,
    tree: pygame.Surface,
    house_front: pygame.Surface,
    window_low: pygame.Surface,
) -> pygame.Surface:
    surface = pygame.Surface(BACKGROUND_SIZE, pygame.SRCALPHA)
    gradient_fill(surface, pygame.Rect(0, 0, 1280, 520), (121, 148, 190), (232, 203, 170))
    surface.blit(fit_to_box(hill, 1480, 220), hill.get_rect(midbottom=(640, 300)))
    for x in (140, 300, 980, 1140):
        surface.blit(tree, tree.get_rect(midbottom=(x, 360)))
    guard_house = fit_to_box(house_front, 178, 202)
    surface.blit(guard_house, guard_house.get_rect(midbottom=(1040, 352)))
    surface.blit(window_low, window_low.get_rect(midbottom=(1040, 300)))
    pygame.draw.rect(surface, (97, 101, 108), pygame.Rect(0, 362, 1280, 158))
    pygame.draw.rect(surface, (205, 181, 123), pygame.Rect(0, 360, 1280, 8))
    for x in range(0, 1280, 96):
        pygame.draw.rect(surface, (245, 226, 166), pygame.Rect(x + 14, 432, 48, 10), border_radius=5)
    return surface


def make_folder_icon(color: tuple[int, int, int], label: str) -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.rect(surface, shift_color(color, -28), pygame.Rect(44, 74, 168, 34), border_radius=12)
    pygame.draw.rect(surface, color, pygame.Rect(32, 100, 192, 116), border_radius=22)
    pygame.draw.rect(surface, shift_color(color, -50), pygame.Rect(32, 100, 192, 116), width=4, border_radius=22)
    for index in range(3):
        pygame.draw.line(surface, (240, 244, 248), (74, 132 + index * 22), (182, 132 + index * 22), 5)
    pygame.draw.circle(surface, shift_color(color, -60), (186, 164), 28)
    return surface


def make_console_icon() -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.rect(surface, (60, 67, 82), pygame.Rect(38, 104, 180, 102), border_radius=20)
    pygame.draw.rect(surface, (22, 25, 31), pygame.Rect(54, 62, 148, 82), border_radius=16)
    pygame.draw.rect(surface, (31, 196, 187), pygame.Rect(66, 76, 54, 18), border_radius=8)
    pygame.draw.rect(surface, (120, 222, 255), pygame.Rect(132, 76, 48, 18), border_radius=8)
    for row in range(2):
        for col in range(4):
            pygame.draw.rect(
                surface,
                (235, 200, 112),
                pygame.Rect(64 + col * 32, 118 + row * 28, 20, 16),
                border_radius=4,
            )
    pygame.draw.rect(surface, (38, 42, 51), pygame.Rect(96, 206, 64, 24), border_radius=10)
    return surface


def make_crate_icon(box: pygame.Surface) -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    rect = box.get_rect(center=(128, 148))
    surface.blit(box, rect)
    pygame.draw.rect(surface, (238, 235, 221), pygame.Rect(84, 108, 88, 36), border_radius=8)
    pygame.draw.rect(surface, (154, 68, 62), pygame.Rect(100, 122, 56, 8), border_radius=4)
    return surface


def make_bag_icon(color: tuple[int, int, int], *, tag: str) -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.arc(surface, shift_color(color, -42), pygame.Rect(74, 52, 108, 80), math.pi, math.tau, 8)
    pygame.draw.rect(surface, color, pygame.Rect(46, 92, 164, 118), border_radius=30)
    pygame.draw.rect(surface, shift_color(color, -52), pygame.Rect(46, 92, 164, 118), width=5, border_radius=30)
    pygame.draw.rect(surface, shift_color(color, 28), pygame.Rect(46, 92, 164, 26), border_radius=12)
    tag_color = (244, 241, 233) if tag != "+" else (248, 232, 232)
    render_simple_mark(surface, tag_color, tag, pygame.Rect(92, 132, 72, 48))
    return surface


def make_blade_icon() -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.rect(surface, (84, 58, 44), pygame.Rect(114, 128, 28, 74), border_radius=8)
    pygame.draw.rect(surface, (128, 86, 62), pygame.Rect(104, 114, 48, 24), border_radius=10)
    pygame.draw.polygon(surface, (219, 224, 230), [(128, 34), (164, 122), (128, 178), (92, 122)])
    pygame.draw.polygon(surface, (171, 183, 194), [(128, 44), (150, 118), (128, 160), (106, 118)])
    return surface


def make_gun_icon() -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.rect(surface, (62, 70, 81), pygame.Rect(62, 110, 130, 30), border_radius=10)
    pygame.draw.rect(surface, (46, 53, 64), pygame.Rect(168, 98, 28, 14), border_radius=6)
    pygame.draw.rect(surface, (62, 70, 81), pygame.Rect(92, 132, 26, 56), border_radius=8)
    pygame.draw.rect(surface, (46, 53, 64), pygame.Rect(108, 140, 34, 18), border_radius=8)
    return surface


def make_pen_device_icon() -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.rect(surface, (88, 96, 111), pygame.Rect(54, 106, 148, 32), border_radius=16)
    pygame.draw.rect(surface, (210, 90, 82), pygame.Rect(176, 106, 42, 32), border_radius=16)
    pygame.draw.rect(surface, (244, 239, 229), pygame.Rect(42, 114, 20, 16), border_radius=8)
    pygame.draw.circle(surface, (94, 214, 208), (82, 122), 10)
    return surface


def make_jammer_icon() -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.rect(surface, (74, 82, 96), pygame.Rect(76, 122, 104, 68), border_radius=18)
    pygame.draw.rect(surface, (37, 45, 56), pygame.Rect(96, 142, 64, 28), border_radius=10)
    pygame.draw.line(surface, (225, 190, 108), (128, 122), (128, 64), 8)
    for offset in (0, 26, 52):
        pygame.draw.arc(
            surface,
            (90, 214, 204),
            pygame.Rect(84 - offset // 2, 42 - offset // 2, 88 + offset, 60 + offset),
            math.pi,
            math.tau,
            4,
        )
    return surface


def make_rig_icon() -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.rect(surface, (72, 78, 86), pygame.Rect(90, 88, 76, 108), border_radius=14)
    pygame.draw.rect(surface, (37, 44, 56), pygame.Rect(104, 102, 48, 28), border_radius=8)
    pygame.draw.rect(surface, (90, 214, 204), pygame.Rect(110, 108, 36, 10), border_radius=5)
    pygame.draw.line(surface, (184, 190, 201), (128, 88), (88, 48), 6)
    pygame.draw.line(surface, (184, 190, 201), (128, 88), (168, 48), 6)
    pygame.draw.line(surface, (225, 190, 108), (88, 48), (88, 28), 5)
    pygame.draw.line(surface, (225, 190, 108), (168, 48), (168, 22), 5)
    for end_x in (76, 180):
        pygame.draw.arc(surface, (90, 214, 204), pygame.Rect(end_x - 24, 6, 48, 36), math.pi, math.tau, 4)
    return surface


def make_round_table_icon() -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.ellipse(surface, (164, 119, 84), pygame.Rect(42, 86, 172, 66))
    pygame.draw.ellipse(surface, (115, 80, 56), pygame.Rect(42, 86, 172, 66), 5)
    for x in (88, 128, 168):
        pygame.draw.rect(surface, (108, 74, 54), pygame.Rect(x, 148, 12, 60), border_radius=6)
    pygame.draw.rect(surface, (123, 88, 64), pygame.Rect(108, 146, 40, 16), border_radius=8)
    return surface


def make_clock_icon(clock: pygame.Surface) -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    surface.blit(clock, clock.get_rect(center=(128, 128)))
    pygame.draw.rect(surface, (124, 96, 62), pygame.Rect(120, 188, 16, 32), border_radius=6)
    return surface


def make_window_icon(window: pygame.Surface) -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.rect(surface, (180, 176, 166), pygame.Rect(56, 72, 144, 126), border_radius=18)
    pygame.draw.rect(surface, (98, 87, 72), pygame.Rect(60, 76, 136, 118), width=6, border_radius=16)
    surface.blit(window, window.get_rect(center=(128, 136)))
    return surface


def make_locked_door_icon(
    door_top: pygame.Surface,
    door_mid: pygame.Surface,
) -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    surface.blit(door_top, door_top.get_rect(midtop=(128, 44)))
    surface.blit(door_mid, door_mid.get_rect(midtop=(128, 78)))
    pygame.draw.rect(surface, (210, 180, 102), pygame.Rect(148, 134, 22, 28), border_radius=8)
    pygame.draw.circle(surface, (76, 58, 38), (159, 149), 4)
    return surface


def make_open_door_icon(
    door_top: pygame.Surface,
    door_mid: pygame.Surface,
) -> pygame.Surface:
    surface = pygame.Surface(ICON_SIZE, pygame.SRCALPHA)
    pygame.draw.rect(surface, (42, 46, 53), pygame.Rect(100, 88, 90, 128), border_radius=18)
    tilted = pygame.transform.rotate(door_mid, 10)
    surface.blit(tilted, tilted.get_rect(midbottom=(110, 210)))
    surface.blit(door_top, door_top.get_rect(midtop=(116, 42)))
    return surface


def load_image(path: Path) -> pygame.Surface:
    return pygame.image.load(str(path))


def fit_to_box(surface: pygame.Surface, max_width: int, max_height: int) -> pygame.Surface:
    width, height = surface.get_size()
    if width <= 0 or height <= 0:
        return surface.copy()
    scale = min(max_width / width, max_height / height)
    target = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    if target == (width, height):
        return surface.copy()
    return pygame.transform.smoothscale(surface, target)


def gradient_fill(
    surface: pygame.Surface,
    rect: pygame.Rect,
    top_color: tuple[int, int, int],
    bottom_color: tuple[int, int, int],
) -> None:
    for y in range(rect.height):
        ratio = y / max(rect.height - 1, 1)
        color = (
            int(round(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)),
            int(round(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)),
            int(round(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)),
        )
        pygame.draw.line(surface, color, (rect.x, rect.y + y), (rect.right, rect.y + y))


def vignette_overlay(surface: pygame.Surface, color: tuple[int, int, int, int]) -> None:
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill(color)
    surface.blit(overlay, (0, 0))


def draw_tall_window(
    surface: pygame.Surface,
    position: tuple[int, int],
    assets: tuple[pygame.Surface, pygame.Surface, pygame.Surface],
) -> None:
    top, mid, bottom = assets
    x, y = position
    surface.blit(top, top.get_rect(midtop=(x, y)))
    surface.blit(mid, mid.get_rect(midtop=(x, y + top.get_height() - 6)))
    surface.blit(bottom, bottom.get_rect(midtop=(x, y + top.get_height() + mid.get_height() - 12)))


def draw_door(
    surface: pygame.Surface,
    position: tuple[int, int],
    assets: tuple[pygame.Surface, pygame.Surface],
) -> None:
    top, mid = assets
    x, y = position
    surface.blit(top, top.get_rect(midtop=(x, y)))
    surface.blit(mid, mid.get_rect(midtop=(x, y + top.get_height() - 8)))


def render_simple_mark(
    surface: pygame.Surface,
    color: tuple[int, int, int],
    text: str,
    rect: pygame.Rect,
) -> None:
    if text == "+":
        pygame.draw.rect(surface, color, pygame.Rect(rect.centerx - 8, rect.centery - 22, 16, 44), border_radius=6)
        pygame.draw.rect(surface, color, pygame.Rect(rect.centerx - 22, rect.centery - 8, 44, 16), border_radius=6)
        return

    pygame.draw.rect(surface, color, pygame.Rect(rect.x + 10, rect.y + 6, rect.width - 20, 14), border_radius=7)
    pygame.draw.rect(surface, color, pygame.Rect(rect.x + 18, rect.y + 24, 14, rect.height - 32), border_radius=7)
    pygame.draw.rect(surface, color, pygame.Rect(rect.right - 34, rect.y + 24, 14, rect.height - 32), border_radius=7)
    pygame.draw.rect(surface, color, pygame.Rect(rect.x + 10, rect.bottom - 18, rect.width - 20, 10), border_radius=5)


def save_surface(surface: pygame.Surface, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surface, str(destination))


def shift_color(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    return tuple(max(0, min(255, channel + amount)) for channel in color)


if __name__ == "__main__":
    main()
