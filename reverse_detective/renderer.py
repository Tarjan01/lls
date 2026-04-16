"""Scene rendering for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import pygame

from reverse_detective.game_state import GameSessionState
from reverse_detective.models import ActionOption, Interactable, NPC, SceneState
from reverse_detective.utils.assets import DEFAULT_ASSET_CACHE_ROOT, resolve_cached_asset_path
from reverse_detective.utils.text import clamp_lines, wrap_text


Color = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class PlaceholderStyle:
    fill: Color
    outline: Color
    text: Color
    shadow: Color


class PlaceholderAssetResolver:
    """Placeholder visual resolver that can later be replaced with image assets."""

    _background_palettes = (
        ((17, 26, 43), (52, 69, 97), (102, 85, 73)),
        ((19, 33, 35), (69, 106, 95), (100, 86, 69)),
        ((33, 24, 34), (96, 71, 92), (114, 93, 83)),
    )

    def resolve_background(self, key: str) -> tuple[Color, Color, Color]:
        index = abs(hash(key)) % len(self._background_palettes)
        return self._background_palettes[index]

    def resolve_npc_style(self, key: str) -> PlaceholderStyle:
        return self._style_from_key(key, ((206, 214, 224), (50, 56, 70), (20, 24, 32), (0, 0, 0)))

    def resolve_interactable_style(self, key: str) -> PlaceholderStyle:
        return self._style_from_key(key, ((243, 197, 97), (95, 66, 24), (27, 20, 12), (47, 37, 16)))

    def resolve_player_style(self) -> PlaceholderStyle:
        return PlaceholderStyle((211, 92, 76), (88, 34, 29), (255, 245, 232), (46, 16, 12))

    def _style_from_key(
        self,
        key: str,
        base: tuple[Color, Color, Color, Color],
    ) -> PlaceholderStyle:
        seed = abs(hash(key)) % 31
        fill = _tint(base[0], seed - 15)
        outline = _tint(base[1], seed - 15)
        text = base[2]
        shadow = base[3]
        return PlaceholderStyle(fill, outline, text, shadow)


class Renderer:
    """Pygame renderer for the current scene and UI overlays."""

    def __init__(
        self,
        surface: pygame.Surface,
        width: int,
        height: int,
        play_area_height: int,
        asset_root: Path | None = None,
    ):
        self._surface = surface
        self._width = width
        self._height = height
        self._play_area_height = play_area_height
        self._hud_top = play_area_height
        self._asset_root = (asset_root or DEFAULT_ASSET_CACHE_ROOT).resolve()
        self._image_cache: dict[tuple[str, tuple[int, int]], pygame.Surface] = {}
        self._resolver = PlaceholderAssetResolver()
        self._title_font = pygame.font.SysFont("microsoftyaheiui", 28)
        self._body_font = pygame.font.SysFont("microsoftyaheiui", 20)
        self._small_font = pygame.font.SysFont("microsoftyaheiui", 16)

    def draw(
        self,
        session: GameSessionState,
        mode_label: str,
        elapsed_seconds: float,
        player_label: str,
        story_title: str,
    ) -> None:
        scene = session.current_scene
        self._draw_background(scene)
        self._draw_world(scene, session, elapsed_seconds, player_label)
        self._draw_hud(scene, session, mode_label, story_title)

        active_interactable = session.active_interactable
        if (
            active_interactable is not None
            and not session.loading
            and not scene.is_terminal
            and not session.needs_settlement
        ):
            options = session.available_options_for(active_interactable)
            if options:
                self._draw_option_popup(
                    active_interactable,
                    options,
                    session.selected_option_index,
                )

        if session.error_message:
            self._draw_error_banner(session.error_message)

        if session.loading:
            self._draw_loading_overlay(session, mode_label)

        if scene.is_terminal and scene.ending_text:
            self._draw_ending_overlay(scene.ending_text)

        pygame.display.flip()

    def _draw_background(self, scene: SceneState) -> None:
        background_surface = self._load_asset_surface(
            "background",
            scene.scene.background_image,
            (self._width, self._play_area_height),
            scene.scene.description,
            scene.narrative,
        )
        if background_surface is not None:
            self._surface.blit(background_surface, (0, 0))
            vignette = pygame.Surface((self._width, self._play_area_height), pygame.SRCALPHA)
            vignette.fill((8, 12, 18, 26))
            self._surface.blit(vignette, (0, 0))
            return

        top_color, mid_color, floor_color = self._resolver.resolve_background(
            scene.scene.background_image
        )
        for y in range(self._play_area_height):
            ratio = y / max(self._play_area_height - 1, 1)
            color = _lerp_color(top_color, mid_color, ratio)
            pygame.draw.line(self._surface, color, (0, y), (self._width, y))

        floor_rect = pygame.Rect(0, self._play_area_height - 100, self._width, 100)
        pygame.draw.rect(self._surface, floor_color, floor_rect)
        pygame.draw.rect(self._surface, (220, 230, 245), pygame.Rect(70, 52, 1140, 180), border_radius=18)
        pygame.draw.rect(self._surface, (35, 45, 62), pygame.Rect(88, 70, 1104, 144), border_radius=14)

    def _draw_world(
        self,
        scene: SceneState,
        session: GameSessionState,
        elapsed_seconds: float,
        player_label: str,
    ) -> None:
        for npc in scene.npcs:
            self._draw_npc(npc, elapsed_seconds)

        for interactable in scene.interactables:
            if interactable.state.hidden:
                continue
            active = session.active_interactable_id == interactable.id and not session.needs_settlement
            self._draw_interactable(interactable, active)

        self._draw_player(session.player_position, player_label)

    def _draw_npc(self, npc: NPC, elapsed_seconds: float) -> None:
        style = self._resolver.resolve_npc_style(npc.id)
        x, y = self._resolve_npc_position(npc, elapsed_seconds)
        shadow_rect = pygame.Rect(x - 30, y + 58, 60, 18)

        pygame.draw.ellipse(self._surface, style.shadow, shadow_rect)
        sprite = self._load_asset_surface("npc", npc.image, (132, 132), npc.id, npc.name)
        if sprite is not None:
            sprite_rect = sprite.get_rect(midbottom=(x, y + 42))
            self._surface.blit(sprite, sprite_rect)
            self._draw_label(npc.name, (x, sprite_rect.y - 26), style.text)
            return

        body_rect = pygame.Rect(x - 28, y - 72, 56, 108)
        pygame.draw.rect(self._surface, style.fill, body_rect, border_radius=18)
        pygame.draw.rect(self._surface, style.outline, body_rect, width=3, border_radius=18)
        pygame.draw.circle(self._surface, style.fill, (x, y - 92), 24)
        pygame.draw.circle(self._surface, style.outline, (x, y - 92), 24, width=3)
        self._draw_label(npc.name, (x, y - 134), style.text)

    def _draw_interactable(self, interactable: Interactable, active: bool) -> None:
        style = self._resolver.resolve_interactable_style(interactable.id)
        x, y = interactable.position
        shadow_rect = pygame.Rect(x - 24, y + 18, 48, 14)

        if active:
            pulse = 180 + int(50 * math.sin(pygame.time.get_ticks() / 160))
            glow_surface = pygame.Surface((96, 96), pygame.SRCALPHA)
            pygame.draw.circle(glow_surface, (255, 214, 110, pulse), (48, 48), 40, width=5)
            self._surface.blit(glow_surface, (x - 48, y - 48))

        pygame.draw.ellipse(self._surface, style.shadow, shadow_rect)
        option_labels = " ".join(option.label for option in interactable.options)
        sprite = self._load_asset_surface(
            "interactable",
            interactable.image,
            (82, 82),
            interactable.id,
            interactable.name,
            option_labels,
        )
        if sprite is not None:
            sprite_rect = sprite.get_rect(midbottom=(x, y + 30))
            self._surface.blit(sprite, sprite_rect)
            self._draw_label(interactable.name, (x, sprite_rect.y - 18), style.text)
            return

        rect = pygame.Rect(x - 28, y - 28, 56, 56)
        pygame.draw.rect(self._surface, style.fill, rect, border_radius=14)
        pygame.draw.rect(self._surface, style.outline, rect, width=3, border_radius=14)
        self._draw_label(interactable.name, (x, y - 44), style.text)

    def _draw_player(self, player_position: tuple[float, float], player_label: str) -> None:
        style = self._resolver.resolve_player_style()
        x = int(player_position[0])
        y = int(player_position[1])
        shadow_rect = pygame.Rect(x - 22, y + 24, 44, 14)
        body_rect = pygame.Rect(x - 20, y - 38, 40, 62)

        pygame.draw.ellipse(self._surface, style.shadow, shadow_rect)
        pygame.draw.rect(self._surface, style.fill, body_rect, border_radius=14)
        pygame.draw.rect(self._surface, style.outline, body_rect, width=3, border_radius=14)
        pygame.draw.circle(self._surface, style.fill, (x, y - 54), 17)
        pygame.draw.circle(self._surface, style.outline, (x, y - 54), 17, width=3)
        self._draw_label(player_label, (x, y - 86), style.text)

    def _draw_hud(
        self,
        scene: SceneState,
        session: GameSessionState,
        mode_label: str,
        story_title: str,
    ) -> None:
        hud_rect = pygame.Rect(0, self._hud_top, self._width, self._height - self._hud_top)
        pygame.draw.rect(self._surface, (13, 16, 23), hud_rect)
        pygame.draw.line(
            self._surface,
            (72, 83, 103),
            (0, self._hud_top),
            (self._width, self._hud_top),
            width=2,
        )

        self._blit_lines(
            [f"场景: {scene.scene.description}"],
            self._title_font,
            (36, self._hud_top + 24),
            (242, 238, 229),
        )
        self._blit_lines(
            wrap_text(scene.narrative, self._body_font, 760),
            self._body_font,
            (36, self._hud_top + 72),
            (219, 221, 229),
            line_gap=6,
        )

        if session.local_message:
            self._blit_lines(
                ["本地反馈："] + wrap_text(session.local_message, self._small_font, 760),
                self._small_font,
                (36, self._hud_top + 150),
                (237, 221, 189),
                line_gap=5,
            )

        summary_lines = [
            f"案件: {story_title}",
            f"模式: {mode_label}",
            f"状态: {scene.game_status}",
            f"行动点: {session.remaining_action_points}/{session.action_points_per_round}",
            f"本轮待结算: {len(session.round_actions)}",
            "控制: WASD 移动",
            "交互: 上下切选项，Enter/Space 确认",
            "快捷: 数字键 1-9 直接选项，T 提前结算/重试，R 重开，M 返回菜单，Esc 退出",
        ]
        self._blit_lines(summary_lines, self._small_font, (870, self._hud_top + 30), (197, 205, 219))

        round_lines = ["本轮行动:"]
        if session.round_actions:
            for record in session.round_actions[-5:]:
                round_lines.append(f"{record.turn_index}. {record.label}")
        else:
            round_lines.append("尚未消耗行动点")
        self._blit_lines(round_lines, self._small_font, (870, self._hud_top + 190), (237, 221, 189))

        settled_lines = ["已结算记录:"]
        if session.settled_action_history:
            for record in session.settled_action_history[-4:]:
                settled_lines.append(f"{record.turn_index}. {record.label}")
        else:
            settled_lines.append("暂无")
        self._blit_lines(
            settled_lines,
            self._small_font,
            (1060, self._hud_top + 190),
            (215, 219, 228),
        )

        if session.needs_settlement and not session.loading and not scene.is_terminal:
            hint = self._small_font.render("本轮行动点已耗尽，按 T 立即结算。", True, (238, 199, 132))
            self._surface.blit(hint, (36, self._height - 36))

    def _draw_option_popup(
        self,
        interactable: Interactable,
        options: tuple[ActionOption, ...],
        selected_index: int,
    ) -> None:
        popup_width = 400
        popup_height = 56 + len(options) * 40
        popup_rect = pygame.Rect(self._width - popup_width - 28, 26, popup_width, popup_height)
        pygame.draw.rect(self._surface, (12, 16, 24), popup_rect, border_radius=18)
        pygame.draw.rect(self._surface, (120, 135, 166), popup_rect, width=2, border_radius=18)

        title = self._title_font.render(interactable.name, True, (245, 236, 222))
        self._surface.blit(title, (popup_rect.x + 22, popup_rect.y + 18))

        for index, option in enumerate(options):
            option_rect = pygame.Rect(
                popup_rect.x + 18,
                popup_rect.y + 56 + index * 38,
                popup_rect.width - 36,
                32,
            )
            is_selected = index == selected_index
            fill = (227, 197, 124) if is_selected else (35, 43, 61)
            text_color = (28, 22, 15) if is_selected else (226, 230, 238)
            pygame.draw.rect(self._surface, fill, option_rect, border_radius=10)
            label = self._body_font.render(f"{index + 1}. {option.label}", True, text_color)
            self._surface.blit(label, (option_rect.x + 12, option_rect.y + 5))

    def _draw_loading_overlay(self, session: GameSessionState, mode_label: str) -> None:
        overlay = pygame.Surface((self._width, self._play_area_height), pygame.SRCALPHA)
        overlay.fill((8, 10, 15, 150))
        self._surface.blit(overlay, (0, 0))

        title_text = (
            "AI 正在生成初始场景…"
            if not session.round_actions and not session.settled_action_history
            else "AI 正在结算本轮行动…"
        )
        subtitle_text = (
            "将根据本轮行动点刷新场景与裁决结果。"
            if session.round_actions
            else "正在加载本局的初始空间布局与角色状态。"
        )
        text = self._title_font.render(title_text, True, (245, 240, 228))
        mode = self._body_font.render(f"当前模式: {mode_label}", True, (219, 224, 234))
        hint = self._small_font.render(subtitle_text, True, (228, 211, 182))
        self._surface.blit(text, (self._width // 2 - text.get_width() // 2, 170))
        self._surface.blit(mode, (self._width // 2 - mode.get_width() // 2, 216))
        self._surface.blit(hint, (self._width // 2 - hint.get_width() // 2, 250))

    def _draw_ending_overlay(self, ending_text: str) -> None:
        overlay = pygame.Surface((self._width, self._play_area_height), pygame.SRCALPHA)
        overlay.fill((7, 7, 10, 198))
        self._surface.blit(overlay, (0, 0))

        title = self._title_font.render("结局已达成", True, (245, 236, 220))
        self._surface.blit(title, (self._width // 2 - title.get_width() // 2, 96))
        self._blit_lines(
            wrap_text(ending_text, self._body_font, 720),
            self._body_font,
            (self._width // 2 - 360, 150),
            (232, 236, 244),
            line_gap=8,
        )
        hint = self._small_font.render("按 R 重新开始，按 Esc 退出", True, (233, 200, 131))
        self._surface.blit(hint, (self._width // 2 - hint.get_width() // 2, 330))

    def _draw_error_banner(self, message: str) -> None:
        banner_rect = pygame.Rect(24, 18, self._width - 48, 46)
        pygame.draw.rect(self._surface, (134, 34, 30), banner_rect, border_radius=12)
        pygame.draw.rect(self._surface, (255, 196, 184), banner_rect, width=2, border_radius=12)
        preview = self._fit_text(message, self._small_font, banner_rect.width - 28)
        text = self._small_font.render(preview, True, (255, 242, 236))
        self._surface.blit(text, (banner_rect.x + 14, banner_rect.y + 13))

    def _load_asset_surface(
        self,
        asset_kind: str,
        asset_ref: str,
        size: tuple[int, int],
        *hint_texts: str,
    ) -> pygame.Surface | None:
        asset_path = resolve_cached_asset_path(asset_kind, asset_ref, self._asset_root, *hint_texts)
        if asset_path is None or not asset_path.is_file():
            return None

        cache_key = (str(asset_path), size)
        cached = self._image_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            loaded = pygame.image.load(str(asset_path))
            if loaded.get_alpha() is not None:
                loaded = loaded.convert_alpha()
            else:
                loaded = loaded.convert()
            if loaded.get_size() != size:
                loaded = pygame.transform.smoothscale(loaded, size)
        except Exception:
            return None

        self._image_cache[cache_key] = loaded
        return loaded

    def _resolve_npc_position(self, npc: NPC, elapsed_seconds: float) -> tuple[int, int]:
        if not npc.patrol:
            return npc.position

        speed = 78.0
        points = [npc.position, *npc.patrol]
        segments = list(zip(points, points[1:]))
        if not segments:
            return npc.position

        lengths = [
            math.dist((start[0], start[1]), (end[0], end[1])) for start, end in segments
        ]
        total_length = sum(lengths)
        if total_length <= 0:
            return npc.position

        distance = (elapsed_seconds * speed) % total_length
        traversed = 0.0
        for (start, end), length in zip(segments, lengths):
            if traversed + length >= distance:
                ratio = 0.0 if length == 0 else (distance - traversed) / length
                x = int(start[0] + (end[0] - start[0]) * ratio)
                y = int(start[1] + (end[1] - start[1]) * ratio)
                return x, y
            traversed += length

        return npc.position

    def _draw_label(self, text: str, position: tuple[int, int], color: Color) -> None:
        label = self._small_font.render(text, True, color)
        self._surface.blit(label, (position[0] - label.get_width() // 2, position[1]))

    def _fit_text(self, text: str, font: Any, max_width: int) -> str:
        if max_width <= 0 or font.size(text)[0] <= max_width:
            return text

        candidate = text
        while candidate and font.size(candidate + "...")[0] > max_width:
            candidate = candidate[:-1]
        return (candidate or "") + "..."

    def _blit_lines(
        self,
        lines: list[str],
        font: Any,
        position: tuple[int, int],
        color: Color,
        line_gap: int = 4,
    ) -> None:
        x, y = position
        for line in lines:
            rendered = font.render(line, True, color)
            self._surface.blit(rendered, (x, y))
            y += rendered.get_height() + line_gap


def _lerp_color(left: Color, right: Color, ratio: float) -> Color:
    return (
        int(left[0] + (right[0] - left[0]) * ratio),
        int(left[1] + (right[1] - left[1]) * ratio),
        int(left[2] + (right[2] - left[2]) * ratio),
    )


def _tint(color: Color, delta: int) -> Color:
    return tuple(max(0, min(255, channel + delta)) for channel in color)


class MenuRenderer:
    """Renderer for the main menu, dossier browser, settings and modal overlays."""

    def __init__(self, surface: pygame.Surface, width: int, height: int):
        self._surface = surface
        self._width = width
        self._height = height
        self._display_font = pygame.font.SysFont("georgia", 46, bold=True)
        self._hero_font = pygame.font.SysFont("georgia", 72, bold=True)
        self._title_font = pygame.font.SysFont("microsoftyaheiui", 28, bold=True)
        self._body_font = pygame.font.SysFont("microsoftyaheiui", 20)
        self._small_font = pygame.font.SysFont("microsoftyaheiui", 15)

    def draw_main_menu(
        self,
        background: Any,
        options: list[str],
        selected_index: int,
        status_text: str | None,
    ) -> None:
        self._draw_background()
        self._draw_chrome(background.game_title, background.game_subtitle, background.operator_name)

        left_panel = pygame.Rect(48, 150, 560, 470)
        right_panel = pygame.Rect(644, 150, 588, 470)
        self._panel(left_panel, (16, 21, 28))
        self._panel(right_panel, (27, 22, 19))

        hero = self._hero_font.render("案件模拟台", True, (243, 232, 207))
        self._surface.blit(hero, (82, 182))
        intro_lines = clamp_lines(
            wrap_text(background.menu_intro, self._body_font, left_panel.width - 58),
            4,
        )
        self._blit_lines(intro_lines, self._body_font, (82, 276), (232, 235, 239), 8)

        self._section_title("江川的动机", 82, 394)
        background_lines = clamp_lines(
            wrap_text(background.background, self._small_font, left_panel.width - 58),
            7,
        )
        self._blit_lines(background_lines, self._small_font, (82, 430), (208, 214, 224), 6)

        self._section_title("主菜单", 674, 188)
        menu_intro = self._small_font.render("先选择你的行动方向，再进入具体卷宗。", True, (224, 225, 232))
        self._surface.blit(menu_intro, (674, 226))

        for index, option in enumerate(options):
            option_rect = pygame.Rect(674, 276 + index * 88, 516, 66)
            selected = index == selected_index
            fill = (228, 193, 127) if selected else (41, 47, 58)
            border = (246, 226, 193) if selected else (103, 113, 126)
            text_color = (29, 22, 15) if selected else (236, 239, 244)
            pygame.draw.rect(self._surface, fill, option_rect, border_radius=18)
            pygame.draw.rect(self._surface, border, option_rect, width=2, border_radius=18)
            label = self._title_font.render(option, True, text_color)
            hint = self._small_font.render(self._main_menu_hint(option), True, text_color)
            self._surface.blit(label, (option_rect.x + 20, option_rect.y + 14))
            self._surface.blit(hint, (option_rect.x + 22, option_rect.y + 42))

        footer = "主菜单控制: 上下切换 | Enter 确认 | Esc 退出"
        self._draw_footer(footer, status_text)
        pygame.display.flip()

    def draw_story_browser(
        self,
        background: Any,
        story: Any,
        role: Any,
        story_index: int,
        story_count: int,
        focus: str,
        detail_modal: Any | None,
    ) -> None:
        self._draw_background()
        self._draw_chrome(background.game_title, "卷宗选择", background.operator_name)

        left = pygame.Rect(42, 126, 548, 520)
        right = pygame.Rect(620, 126, 586, 520)
        self._panel(left, (17, 22, 28))
        self._panel(right, (25, 21, 18))

        self._section_title(f"卷宗 {story_index + 1}/{story_count}", left.x + 22, left.y + 18)
        self._draw_summary_card(
            rect=pygame.Rect(left.x + 20, left.y + 58, left.width - 40, 412),
            title=story.title,
            subtitle=story.subtitle,
            accent=(225, 196, 131),
            body_blocks=[
                f"地点: {story.location}",
                f"死者: {story.victim_name}",
                story.core_case,
                story.opening_hook,
            ],
            focused=focus == "story",
        )
        ranking_text = " | ".join(rank.rank for rank in story.rankings[:4])
        ranking_label = self._small_font.render(
            self._fit_text(f"评级: {ranking_text}", self._small_font, left.width - 48),
            True,
            (203, 210, 220),
        )
        self._surface.blit(ranking_label, (left.x + 24, left.bottom - 40))

        self._section_title("嫌疑人身份", right.x + 22, right.y + 18)
        self._draw_summary_card(
            rect=pygame.Rect(right.x + 20, right.y + 58, right.width - 40, 266),
            title=role.display_name,
            subtitle=role.primary_tool_name,
            accent=(226, 177, 139),
            body_blocks=[
                role.background,
                f"动机: {role.motive}",
                f"隐藏目标: {role.hidden_objective}",
            ],
            focused=focus == "role",
        )
        self._draw_role_strip(story.roles, role, right.x + 20, right.y + 344, right.width - 40)

        footer = "卷宗页控制: 左右换卷宗 | 上下换身份 | Tab 切换焦点 | Enter 查看详情 | Space 开始案件 | Backspace 返回"
        self._draw_footer(footer, None)
        if detail_modal is not None:
            self._draw_detail_modal(detail_modal)
        pygame.display.flip()

    def draw_settings(
        self,
        background: Any,
        fields: list[tuple[str, str, str]],
        selected_index: int,
        draft: Any,
        editing_field: str | None,
        input_buffer: str,
        status_text: str | None,
    ) -> None:
        self._draw_background()
        self._draw_chrome(background.game_title, "选项设置", background.operator_name)

        panel = pygame.Rect(88, 126, self._width - 176, 520)
        self._panel(panel, (16, 21, 28))
        self._section_title("运行与 AI 请求设置", panel.x + 24, panel.y + 18)

        header = self._small_font.render(
            "包含 AI 请求地址、API Key、模型、回退策略以及基础显示设置。选中后按 Enter 编辑，布尔项可直接切换。",
            True,
            (219, 224, 231),
        )
        self._surface.blit(header, (panel.x + 24, panel.y + 58))

        for index, (field_name, label, field_kind) in enumerate(fields):
            row = pygame.Rect(panel.x + 24, panel.y + 96 + index * 52, panel.width - 48, 42)
            selected = index == selected_index
            fill = (228, 193, 127) if selected else (34, 41, 52)
            border = (244, 227, 192) if selected else (97, 109, 123)
            text_color = (28, 22, 15) if selected else (236, 240, 245)
            pygame.draw.rect(self._surface, fill, row, border_radius=12)
            pygame.draw.rect(self._surface, border, row, width=2, border_radius=12)

            name_label = self._small_font.render(
                self._fit_text(label, self._small_font, 250),
                True,
                text_color,
            )
            value_label = self._small_font.render(
                self._fit_text(
                    self._format_setting_value(field_name, field_kind, draft),
                    self._small_font,
                    row.width - 320,
                ),
                True,
                text_color,
            )
            self._surface.blit(name_label, (row.x + 14, row.y + 11))
            self._surface.blit(value_label, (row.x + 280, row.y + 11))

        tips = [
            "必要设置:",
            "1. 请求 URL / Base URL",
            "2. API Key",
            "3. 模型名与回退策略",
            "4. 窗口标题与帧率",
        ]
        self._blit_lines(tips, self._small_font, (panel.x + 24, panel.bottom - 112), (230, 210, 167), 5)
        footer = "设置页控制: 上下切换 | Enter 编辑/切换 | 左右切换布尔值 | S 保存 | D 放弃修改 | Backspace 返回"
        self._draw_footer(footer, status_text)

        if editing_field is not None:
            self._draw_input_modal(
                title=self._field_label(editing_field, fields),
                value=input_buffer,
                masked=editing_field == "api_key",
            )
        pygame.display.flip()

    def _draw_background(self) -> None:
        top = (11, 24, 28)
        bottom = (53, 39, 30)
        for y in range(self._height):
            ratio = y / max(self._height - 1, 1)
            color = _lerp_color(top, bottom, ratio)
            pygame.draw.line(self._surface, color, (0, y), (self._width, y))

        for x in range(80, self._width, 220):
            pygame.draw.line(self._surface, (88, 50, 42), (x, 0), (x - 120, self._height), width=1)
        for y in range(110, self._height, 150):
            pygame.draw.line(self._surface, (29, 51, 54), (0, y), (self._width, y - 50), width=1)

    def _draw_chrome(self, title_text: str, subtitle_text: str, operator_name: str) -> None:
        header_rect = pygame.Rect(34, 24, self._width - 68, 84)
        pygame.draw.rect(self._surface, (19, 24, 33), header_rect, border_radius=20)
        pygame.draw.rect(self._surface, (201, 169, 111), header_rect, width=2, border_radius=20)

        title = self._display_font.render(title_text, True, (244, 232, 207))
        subtitle = self._small_font.render(subtitle_text, True, (212, 213, 222))
        badge = self._small_font.render(f"操作员 {operator_name}", True, (36, 28, 18))

        badge_rect = pygame.Rect(self._width - 208, 42, 154, 34)
        pygame.draw.rect(self._surface, (228, 194, 131), badge_rect, border_radius=12)
        self._surface.blit(title, (58, 34))
        self._surface.blit(subtitle, (60, 78))
        self._surface.blit(badge, (badge_rect.x + 18, badge_rect.y + 9))

    def _draw_summary_card(
        self,
        rect: pygame.Rect,
        title: str,
        subtitle: str,
        accent: Color,
        body_blocks: list[str],
        focused: bool,
    ) -> None:
        fill = (36, 42, 52) if not focused else (51, 58, 70)
        border = accent if focused else (96, 106, 118)
        pygame.draw.rect(self._surface, fill, rect, border_radius=18)
        pygame.draw.rect(self._surface, border, rect, width=2, border_radius=18)

        title_surface = self._title_font.render(title, True, (244, 240, 233))
        subtitle_surface = self._small_font.render(subtitle, True, accent)
        self._surface.blit(title_surface, (rect.x + 18, rect.y + 16))
        self._surface.blit(subtitle_surface, (rect.x + 18, rect.y + 54))

        y = rect.y + 92
        for block in body_blocks:
            lines = clamp_lines(wrap_text(block, self._small_font, rect.width - 36), 4)
            self._blit_lines(lines, self._small_font, (rect.x + 18, y), (221, 225, 231), 4)
            y += len(lines) * 22 + 12
            if y > rect.bottom - 40:
                break

        hint = self._small_font.render("Enter 查看完整内容", True, accent)
        self._surface.blit(hint, (rect.x + 18, rect.bottom - 28))

    def _draw_role_strip(self, roles: Any, selected_role: Any, x: int, y: int, width: int) -> None:
        strip = pygame.Rect(x, y, width, 156)
        pygame.draw.rect(self._surface, (18, 21, 27), strip, border_radius=18)
        pygame.draw.rect(self._surface, (106, 112, 122), strip, width=2, border_radius=18)
        row_height = 28
        for index, role in enumerate(roles):
            row_y = strip.y + 16 + index * 30
            if row_y + row_height > strip.bottom - 12:
                break
            card = pygame.Rect(strip.x + 14, row_y, strip.width - 28, row_height)
            selected = role.id == selected_role.id
            fill = (228, 193, 127) if selected else (39, 44, 54)
            border = (244, 228, 198) if selected else (99, 109, 124)
            title_color = (29, 22, 16) if selected else (239, 241, 245)
            body_color = (60, 47, 29) if selected else (192, 200, 212)
            pygame.draw.rect(self._surface, fill, card, border_radius=16)
            pygame.draw.rect(self._surface, border, card, width=2, border_radius=16)

            title = self._small_font.render(
                self._fit_text(role.display_name, self._small_font, 220),
                True,
                title_color,
            )
            tool = self._small_font.render(
                self._fit_text(role.primary_tool_name, self._small_font, 250),
                True,
                body_color,
            )
            self._surface.blit(title, (card.x + 12, card.y + 6))
            self._surface.blit(tool, (card.right - tool.get_width() - 12, card.y + 6))

    def _draw_detail_modal(self, modal: Any) -> None:
        overlay = pygame.Surface((self._width, self._height), pygame.SRCALPHA)
        overlay.fill((8, 10, 14, 176))
        self._surface.blit(overlay, (0, 0))

        rect = pygame.Rect(148, 86, self._width - 296, self._height - 172)
        pygame.draw.rect(self._surface, (16, 18, 24), rect, border_radius=22)
        pygame.draw.rect(self._surface, (219, 188, 132), rect, width=2, border_radius=22)

        title = self._title_font.render(modal.title, True, (247, 233, 204))
        subtitle = self._small_font.render(modal.subtitle, True, (220, 223, 232))
        self._surface.blit(title, (rect.x + 24, rect.y + 20))
        self._surface.blit(subtitle, (rect.x + 24, rect.y + 58))

        lines: list[str] = []
        for block in modal.body_lines:
            if not block:
                lines.append(" ")
                continue
            lines.extend(wrap_text(block, self._small_font, rect.width - 48))
        lines = clamp_lines(lines, 22)
        self._blit_lines(lines, self._small_font, (rect.x + 24, rect.y + 98), (232, 235, 241), 6)
        footer = self._small_font.render(
            self._fit_text(modal.footer, self._small_font, rect.width - 48),
            True,
            (238, 199, 132),
        )
        self._surface.blit(footer, (rect.x + 24, rect.bottom - 32))

    def _draw_input_modal(self, title: str, value: str, masked: bool) -> None:
        overlay = pygame.Surface((self._width, self._height), pygame.SRCALPHA)
        overlay.fill((6, 8, 12, 176))
        self._surface.blit(overlay, (0, 0))

        rect = pygame.Rect(236, 220, self._width - 472, 172)
        pygame.draw.rect(self._surface, (16, 18, 24), rect, border_radius=22)
        pygame.draw.rect(self._surface, (219, 188, 132), rect, width=2, border_radius=22)
        title_surface = self._title_font.render(title, True, (247, 233, 204))
        subtitle = self._small_font.render("Enter 保存输入 | Esc 取消", True, (220, 223, 232))
        self._surface.blit(title_surface, (rect.x + 24, rect.y + 20))
        self._surface.blit(subtitle, (rect.x + 24, rect.y + 56))

        input_rect = pygame.Rect(rect.x + 22, rect.y + 96, rect.width - 44, 44)
        pygame.draw.rect(self._surface, (37, 42, 52), input_rect, border_radius=12)
        pygame.draw.rect(self._surface, (226, 193, 128), input_rect, width=2, border_radius=12)
        display_value = value if not masked else "*" * len(value)
        preview = self._fit_text(display_value or " ", self._small_font, input_rect.width - 24)
        value_surface = self._small_font.render(preview or " ", True, (244, 240, 233))
        self._surface.blit(value_surface, (input_rect.x + 12, input_rect.y + 13))

    def _panel(self, rect: pygame.Rect, fill: Color) -> None:
        pygame.draw.rect(self._surface, fill, rect, border_radius=18)
        pygame.draw.rect(self._surface, (123, 118, 103), rect, width=2, border_radius=18)

    def _section_title(self, text: str, x: int, y: int) -> None:
        rendered = self._title_font.render(text, True, (243, 234, 219))
        self._surface.blit(rendered, (x, y))

    def _section_subtitle(self, text: str, x: int, y: int) -> None:
        rendered = self._small_font.render(text, True, (235, 192, 125))
        self._surface.blit(rendered, (x, y))

    def _draw_footer(self, text: str, status_text: str | None) -> None:
        footer_rect = pygame.Rect(34, self._height - 48, self._width - 68, 30)
        footer = self._small_font.render(
            self._fit_text(text, self._small_font, footer_rect.width - 320),
            True,
            (224, 229, 235),
        )
        self._surface.blit(footer, (footer_rect.x + 4, footer_rect.y + 4))
        if status_text:
            status = self._small_font.render(
                self._fit_text(status_text, self._small_font, 300),
                True,
                (237, 203, 138),
            )
            self._surface.blit(status, (footer_rect.right - status.get_width(), footer_rect.y + 4))

    def _field_label(self, field_name: str, fields: list[tuple[str, str, str]]) -> str:
        for candidate_name, label, _ in fields:
            if candidate_name == field_name:
                return label
        return field_name

    def _format_setting_value(self, field_name: str, field_kind: str, draft: Any) -> str:
        value = getattr(draft, field_name)
        if field_kind == "bool":
            return "开启" if value else "关闭"
        if field_name == "api_key":
            return self._mask_secret(str(value))
        return str(value) or "(空)"

    def _main_menu_hint(self, option: str) -> str:
        hints = {
            "开始游戏": "进入卷宗选择，查看简介并决定要扮演的身份。",
            "选项设置": "调整请求 URL、API Key、模型与基础运行参数。",
            "退出游戏": "关闭案件模拟台。",
        }
        return hints.get(option, "")

    def _mask_secret(self, value: str) -> str:
        if not value:
            return "(未设置)"
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"

    def _fit_text(self, text: str, font: Any, max_width: int) -> str:
        if max_width <= 0 or font.size(text)[0] <= max_width:
            return text

        candidate = text
        while candidate and font.size(candidate + "…")[0] > max_width:
            candidate = candidate[:-1]
        return (candidate or "") + "…"

    def _blit_lines(
        self,
        lines: list[str],
        font: Any,
        position: tuple[int, int],
        color: Color,
        line_gap: int = 4,
    ) -> None:
        x, y = position
        for line in lines:
            rendered = font.render(line, True, color)
            self._surface.blit(rendered, (x, y))
            y += rendered.get_height() + line_gap
