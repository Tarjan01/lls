"""Scene rendering for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import pygame

from reverse_detective.game_state import GameSessionState
from reverse_detective.models import Interactable, NPC, SceneState
from reverse_detective.utils.text import wrap_text


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

    def __init__(self, surface: pygame.Surface, width: int, height: int, play_area_height: int):
        self._surface = surface
        self._width = width
        self._height = height
        self._play_area_height = play_area_height
        self._hud_top = play_area_height
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

        if session.active_interactable is not None and not session.loading and not scene.is_terminal:
            self._draw_option_popup(session.active_interactable, session.selected_option_index)

        if session.error_message:
            self._draw_error_banner(session.error_message)

        if session.loading:
            self._draw_loading_overlay(mode_label)

        if scene.is_terminal and scene.ending_text:
            self._draw_ending_overlay(scene.ending_text)

        pygame.display.flip()

    def _draw_background(self, scene: SceneState) -> None:
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
            active = session.active_interactable_id == interactable.id
            self._draw_interactable(interactable, active)

        self._draw_player(session.player_position, player_label)

    def _draw_npc(self, npc: NPC, elapsed_seconds: float) -> None:
        style = self._resolver.resolve_npc_style(npc.id)
        x, y = self._resolve_npc_position(npc, elapsed_seconds)
        shadow_rect = pygame.Rect(x - 30, y + 58, 60, 18)
        body_rect = pygame.Rect(x - 28, y - 72, 56, 108)

        pygame.draw.ellipse(self._surface, style.shadow, shadow_rect)
        pygame.draw.rect(self._surface, style.fill, body_rect, border_radius=18)
        pygame.draw.rect(self._surface, style.outline, body_rect, width=3, border_radius=18)
        pygame.draw.circle(self._surface, style.fill, (x, y - 92), 24)
        pygame.draw.circle(self._surface, style.outline, (x, y - 92), 24, width=3)
        self._draw_label(npc.name, (x, y - 134), style.text)

    def _draw_interactable(self, interactable: Interactable, active: bool) -> None:
        style = self._resolver.resolve_interactable_style(interactable.id)
        x, y = interactable.position
        rect = pygame.Rect(x - 28, y - 28, 56, 56)
        shadow_rect = pygame.Rect(x - 24, y + 18, 48, 14)

        if active:
            pulse = 180 + int(50 * math.sin(pygame.time.get_ticks() / 160))
            glow_surface = pygame.Surface((96, 96), pygame.SRCALPHA)
            pygame.draw.circle(glow_surface, (255, 214, 110, pulse), (48, 48), 40, width=5)
            self._surface.blit(glow_surface, (x - 48, y - 48))

        pygame.draw.ellipse(self._surface, style.shadow, shadow_rect)
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
        pygame.draw.line(self._surface, (72, 83, 103), (0, self._hud_top), (self._width, self._hud_top), width=2)

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

        summary_lines = [
            f"案件: {story_title}",
            f"模式: {mode_label}",
            f"状态: {scene.game_status}",
            "控制: WASD 移动",
            "交互: 上下切选项，Enter/Space 确认",
            "快捷: 数字键 1-9 直接选项，R 重开，M 返回菜单，Esc 退出",
        ]
        self._blit_lines(summary_lines, self._small_font, (870, self._hud_top + 30), (197, 205, 219))

        history_lines = ["操作记录:"]
        for record in session.action_history[-4:]:
            history_lines.append(f"{record.turn_index}. {record.label}")
        self._blit_lines(history_lines, self._small_font, (870, self._hud_top + 140), (237, 221, 189))

    def _draw_option_popup(self, interactable: Interactable, selected_index: int) -> None:
        popup_width = 360
        popup_height = 56 + len(interactable.options) * 40
        popup_rect = pygame.Rect(self._width - popup_width - 28, 26, popup_width, popup_height)
        pygame.draw.rect(self._surface, (12, 16, 24), popup_rect, border_radius=18)
        pygame.draw.rect(self._surface, (120, 135, 166), popup_rect, width=2, border_radius=18)

        title = self._title_font.render(interactable.name, True, (245, 236, 222))
        self._surface.blit(title, (popup_rect.x + 22, popup_rect.y + 18))

        for index, option in enumerate(interactable.options):
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

    def _draw_loading_overlay(self, mode_label: str) -> None:
        overlay = pygame.Surface((self._width, self._play_area_height), pygame.SRCALPHA)
        overlay.fill((8, 10, 15, 150))
        self._surface.blit(overlay, (0, 0))

        text = self._title_font.render("AI 正在生成下一幕……", True, (245, 240, 228))
        mode = self._body_font.render(f"当前模式: {mode_label}", True, (219, 224, 234))
        self._surface.blit(text, (self._width // 2 - text.get_width() // 2, 180))
        self._surface.blit(mode, (self._width // 2 - mode.get_width() // 2, 226))

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
        text = self._small_font.render(message, True, (255, 242, 236))
        self._surface.blit(text, (banner_rect.x + 14, banner_rect.y + 13))

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
    """Front-page dossier style menu renderer."""

    def __init__(self, surface: pygame.Surface, width: int, height: int):
        self._surface = surface
        self._width = width
        self._height = height
        self._display_font = pygame.font.SysFont("georgia", 44, bold=True)
        self._title_font = pygame.font.SysFont("microsoftyaheiui", 28, bold=True)
        self._body_font = pygame.font.SysFont("microsoftyaheiui", 19)
        self._small_font = pygame.font.SysFont("microsoftyaheiui", 15)

    def draw(self, story: Any, role: Any, story_index: int, story_count: int) -> None:
        self._draw_background()
        self._draw_header(story, story_index, story_count)
        self._draw_simulation_panel(story)
        self._draw_case_panel(story)
        self._draw_role_panel(story, role)
        self._draw_role_strip(story, role)
        self._draw_footer()
        pygame.display.flip()

    def _draw_background(self) -> None:
        top = (13, 28, 31)
        bottom = (59, 43, 34)
        for y in range(self._height):
            ratio = y / max(self._height - 1, 1)
            color = _lerp_color(top, bottom, ratio)
            pygame.draw.line(self._surface, color, (0, y), (self._width, y))

        for x in range(80, self._width, 220):
            pygame.draw.line(self._surface, (88, 50, 42), (x, 0), (x - 120, self._height), width=1)
        for y in range(110, self._height, 150):
            pygame.draw.line(self._surface, (29, 51, 54), (0, y), (self._width, y - 50), width=1)

    def _draw_header(self, story: Any, story_index: int, story_count: int) -> None:
        header_rect = pygame.Rect(34, 24, self._width - 68, 84)
        pygame.draw.rect(self._surface, (19, 24, 33), header_rect, border_radius=20)
        pygame.draw.rect(self._surface, (201, 169, 111), header_rect, width=2, border_radius=20)

        title = self._display_font.render("REVERSE DETECTIVE", True, (244, 232, 207))
        subtitle = self._small_font.render("江川案件模拟台", True, (212, 213, 222))
        badge = self._small_font.render(
            f"卷宗 {story_index + 1}/{story_count}",
            True,
            (36, 28, 18),
        )

        badge_rect = pygame.Rect(self._width - 172, 42, 118, 34)
        pygame.draw.rect(self._surface, (228, 194, 131), badge_rect, border_radius=12)
        self._surface.blit(title, (58, 34))
        self._surface.blit(subtitle, (60, 78))
        self._surface.blit(badge, (badge_rect.x + 18, badge_rect.y + 9))

        case_title = self._title_font.render(story.title, True, (244, 240, 233))
        case_subtitle = self._small_font.render(story.subtitle, True, (199, 208, 217))
        self._surface.blit(case_title, (490, 42))
        self._surface.blit(case_subtitle, (492, 76))

    def _draw_simulation_panel(self, story: Any) -> None:
        panel = pygame.Rect(34, 130, 356, 390)
        self._panel(panel, (29, 34, 42))
        self._section_title("模拟缘起", panel.x + 22, panel.y + 18)

        operator = self._title_font.render(f"侦探 {story.simulation_operator_name}", True, (241, 230, 206))
        self._surface.blit(operator, (panel.x + 22, panel.y + 54))
        self._blit_lines(
            wrap_text(story.simulation_background, self._body_font, panel.width - 44),
            self._body_font,
            (panel.x + 22, panel.y + 98),
            (224, 227, 233),
            line_gap=6,
        )
        self._blit_lines(
            wrap_text(story.simulation_briefing, self._small_font, panel.width - 44),
            self._small_font,
            (panel.x + 22, panel.y + 268),
            (230, 208, 158),
            line_gap=6,
        )

    def _draw_case_panel(self, story: Any) -> None:
        panel = pygame.Rect(412, 130, 426, 390)
        self._panel(panel, (25, 29, 36))
        self._section_title("案件卷宗", panel.x + 22, panel.y + 18)

        blocks = [
            f"地点: {story.location}",
            f"死者: {story.victim_name}",
            story.core_case,
            story.setting,
        ]
        y = panel.y + 58
        for block in blocks:
            lines = wrap_text(block, self._body_font, panel.width - 44)
            self._blit_lines(lines, self._body_font, (panel.x + 22, y), (228, 231, 236), line_gap=5)
            y += len(lines) * 28 + 16

        badge_rect = pygame.Rect(panel.x + 22, panel.bottom - 86, panel.width - 44, 62)
        pygame.draw.rect(self._surface, (61, 41, 34), badge_rect, border_radius=14)
        pygame.draw.rect(self._surface, (183, 128, 109), badge_rect, width=1, border_radius=14)
        self._blit_lines(
            wrap_text(story.opening_hook, self._small_font, badge_rect.width - 24),
            self._small_font,
            (badge_rect.x + 12, badge_rect.y + 10),
            (245, 233, 225),
            line_gap=4,
        )

    def _draw_role_panel(self, story: Any, role: Any) -> None:
        panel = pygame.Rect(860, 130, 386, 390)
        self._panel(panel, (29, 22, 20))
        self._section_title("嫌疑人身份", panel.x + 22, panel.y + 18)

        title = self._title_font.render(role.display_name, True, (247, 228, 196))
        self._surface.blit(title, (panel.x + 22, panel.y + 54))

        motive_label = self._small_font.render("动机", True, (234, 196, 129))
        self._surface.blit(motive_label, (panel.x + 22, panel.y + 98))
        self._blit_lines(
            wrap_text(role.motive, self._small_font, panel.width - 44),
            self._small_font,
            (panel.x + 22, panel.y + 122),
            (229, 229, 234),
            line_gap=4,
        )

        self._section_subtitle("特殊条件", panel.x + 22, panel.y + 198)
        y = panel.y + 224
        for item in role.special_conditions[:2]:
            bullet = self._small_font.render(f"• {item}", True, (224, 227, 232))
            self._surface.blit(bullet, (panel.x + 22, y))
            y += 22

        self._section_subtitle("专属工具", panel.x + 22, panel.y + 274)
        y = panel.y + 300
        for tool in role.signature_tools[:2]:
            name = self._small_font.render(f"• {tool.name}", True, (247, 212, 140))
            self._surface.blit(name, (panel.x + 22, y))
            y += 20
            self._blit_lines(
                wrap_text(tool.description, self._small_font, panel.width - 58),
                self._small_font,
                (panel.x + 34, y),
                (218, 222, 228),
                line_gap=3,
            )
            y += 38

        hidden = pygame.Rect(panel.x + 20, panel.bottom - 70, panel.width - 40, 50)
        pygame.draw.rect(self._surface, (73, 33, 31), hidden, border_radius=12)
        hidden_title = self._small_font.render("隐藏目标", True, (247, 213, 160))
        hidden_text = self._small_font.render(role.hidden_objective, True, (245, 236, 230))
        self._surface.blit(hidden_title, (hidden.x + 12, hidden.y + 8))
        self._surface.blit(hidden_text, (hidden.x + 12, hidden.y + 26))

    def _draw_role_strip(self, story: Any, selected_role: Any) -> None:
        strip = pygame.Rect(34, 540, self._width - 68, 124)
        self._panel(strip, (18, 21, 27))

        card_width = 286
        gap = 16
        start_x = strip.x + 18
        y = strip.y + 16
        for index, role in enumerate(story.roles):
            x = start_x + index * (card_width + gap)
            if x + card_width > strip.right - 18:
                break
            card = pygame.Rect(x, y, card_width, 90)
            selected = role.id == selected_role.id
            fill = (228, 193, 127) if selected else (39, 44, 54)
            border = (244, 228, 198) if selected else (99, 109, 124)
            title_color = (29, 22, 16) if selected else (239, 241, 245)
            body_color = (60, 47, 29) if selected else (192, 200, 212)
            pygame.draw.rect(self._surface, fill, card, border_radius=16)
            pygame.draw.rect(self._surface, border, card, width=2, border_radius=16)

            title = self._small_font.render(role.display_name, True, title_color)
            strat = self._small_font.render(role.primary_tool_name, True, body_color)
            self._surface.blit(title, (card.x + 14, card.y + 14))
            self._surface.blit(strat, (card.x + 14, card.y + 46))

    def _draw_footer(self) -> None:
        footer_rect = pygame.Rect(34, self._height - 44, self._width - 68, 26)
        text = self._small_font.render(
            "菜单控制: 左右切换卷宗 | 上下切换角色 | Enter 开始案件 | Esc 退出",
            True,
            (224, 229, 235),
        )
        self._surface.blit(text, (footer_rect.x + 4, footer_rect.y + 2))

    def _panel(self, rect: pygame.Rect, fill: Color) -> None:
        pygame.draw.rect(self._surface, fill, rect, border_radius=18)
        pygame.draw.rect(self._surface, (123, 118, 103), rect, width=2, border_radius=18)

    def _section_title(self, text: str, x: int, y: int) -> None:
        rendered = self._title_font.render(text, True, (243, 234, 219))
        self._surface.blit(rendered, (x, y))

    def _section_subtitle(self, text: str, x: int, y: int) -> None:
        rendered = self._small_font.render(text, True, (235, 192, 125))
        self._surface.blit(rendered, (x, y))

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
