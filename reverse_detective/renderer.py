"""Scene rendering for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import pygame

from reverse_detective.game_state import GameSessionState
from reverse_detective.models import ActionOption, Interactable, NPC, SceneState
from reverse_detective.utils.assets import (
    DEFAULT_ASSET_CACHE_ROOT,
    resolve_cached_asset_path,
    resolve_scene_background_path,
)
from reverse_detective.utils.text import fit_text, preview_wrapped_text, wrap_text


Color = tuple[int, int, int]
CHARACTER_RENDER_SCALE = 1.2
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_MENU_ART_PATH = str(PROJECT_ROOT / "assets" / "h_img" / "main.jpg")
PROFILE_SETUP_ART_PATH = str(PROJECT_ROOT / "assets" / "h_img" / "ID.jpg")


@dataclass(frozen=True, slots=True)
class PlaceholderStyle:
    fill: Color
    outline: Color
    text: Color
    shadow: Color


@dataclass(frozen=True, slots=True)
class TooltipTarget:
    rect: pygame.Rect
    text: str
    key: str
    selected: bool = False
    preferred_width: int = 360


@dataclass(frozen=True, slots=True)
class UiActionTarget:
    rect: pygame.Rect
    action: str


class TooltipMixin:
    """Shared selected-text viewer behavior for menu and in-game renderers."""

    _surface: pygame.Surface
    _width: int
    _height: int
    _small_font: Any
    _tooltip_targets: list[TooltipTarget]
    _mouse_pos: tuple[int, int]
    _selected_text_key: str | None
    _selected_text_content: str | None
    _selected_text_preferred_width: int
    _selected_text_scroll: int
    _selected_text_max_scroll: int
    _selected_text_panel_rect: pygame.Rect | None

    def _init_tooltip_state(self) -> None:
        self._tooltip_targets = []
        self._mouse_pos = (0, 0)
        self._selected_text_key = None
        self._selected_text_content = None
        self._selected_text_preferred_width = 360
        self._selected_text_scroll = 0
        self._selected_text_max_scroll = 0
        self._selected_text_panel_rect = None

    def _begin_tooltip_frame(self) -> None:
        self._tooltip_targets = []
        self._mouse_pos = pygame.mouse.get_pos()
        self._selected_text_panel_rect = None

    def _register_tooltip(
        self,
        rect: pygame.Rect,
        text: str,
        *,
        selected: bool = False,
        preferred_width: int = 360,
    ) -> TooltipTarget | None:
        cleaned = text.strip()
        if not cleaned:
            return None
        key = self._tooltip_key(rect, cleaned)
        target = TooltipTarget(
            rect.copy(),
            cleaned,
            key=key,
            selected=selected,
            preferred_width=preferred_width,
        )
        self._tooltip_targets.append(target)
        if self._selected_text_key == key:
            self._selected_text_preferred_width = preferred_width
        return target

    def has_selected_text(self) -> bool:
        return bool(self._selected_text_content)

    def clear_selected_text(self) -> None:
        self._selected_text_key = None
        self._selected_text_content = None
        self._selected_text_scroll = 0
        self._selected_text_max_scroll = 0
        self._selected_text_panel_rect = None

    def handle_text_selection_click(self, position: tuple[int, int]) -> bool:
        target = next(
            (candidate for candidate in reversed(self._tooltip_targets) if candidate.rect.collidepoint(position)),
            None,
        )
        if target is not None:
            self._activate_tooltip_target(target)
            return True

        if self._selected_text_panel_rect is not None and self._selected_text_panel_rect.collidepoint(position):
            return True

        if self.has_selected_text():
            self.clear_selected_text()
            return True

        return False

    def _activate_tooltip_target(self, target: TooltipTarget) -> None:
        self._selected_text_key = target.key
        self._selected_text_content = target.text
        self._selected_text_preferred_width = target.preferred_width
        self._selected_text_scroll = 0
        self._selected_text_max_scroll = 0

    def scroll_selected_text(self, delta_lines: int) -> bool:
        if not self.has_selected_text():
            return False
        self._selected_text_scroll = min(
            max(self._selected_text_scroll + delta_lines, 0),
            self._selected_text_max_scroll,
        )
        return True

    def _draw_tooltip_overlay(self) -> None:
        if not self.has_selected_text() or self._selected_text_content is None:
            return

        selected_target = next(
            (candidate for candidate in self._tooltip_targets if candidate.key == self._selected_text_key),
            None,
        )
        if selected_target is not None:
            highlight_rect = selected_target.rect.inflate(10, 10)
            pygame.draw.rect(self._surface, (244, 220, 171), highlight_rect, width=2, border_radius=10)

        panel_width = min(
            max(self._selected_text_preferred_width + 48, 360),
            max(320, self._width - 72),
        )
        panel_height = min(max(236, self._height // 3), self._height - 116)
        panel_rect = pygame.Rect(
            self._width - panel_width - 28,
            max(92, self._height - panel_height - 74),
            panel_width,
            panel_height,
        )
        self._selected_text_panel_rect = panel_rect

        overlay = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
        overlay.fill((12, 16, 22, 236))
        self._surface.blit(overlay, panel_rect)
        pygame.draw.rect(self._surface, (242, 209, 142), panel_rect, width=2, border_radius=18)

        self._blit_clamped_line(
            self._small_font,
            "鍏ㄦ枃鏌ョ湅",
            (panel_rect.x + 18, panel_rect.y + 14),
            (244, 227, 191),
            panel_rect.width - 36,
        )
        self._blit_clamped_line(
            self._small_font,
            "Mouse-selected text can be read here. Use wheel or arrow keys to scroll; click empty space to close.",
            (panel_rect.x + 18, panel_rect.y + 38),
            (208, 214, 224),
            panel_rect.width - 36,
        )

        body_rect = pygame.Rect(panel_rect.x + 18, panel_rect.y + 68, panel_rect.width - 42, panel_rect.height - 88)
        line_height = self._small_font.get_height() + 6
        wrapped_lines = wrap_text(self._selected_text_content, self._small_font, body_rect.width - 8)
        visible_lines = max(1, body_rect.height // max(line_height, 1))
        self._selected_text_max_scroll = max(0, len(wrapped_lines) - visible_lines)
        self._selected_text_scroll = min(max(self._selected_text_scroll, 0), self._selected_text_max_scroll)

        start_line = self._selected_text_scroll
        end_line = min(len(wrapped_lines), start_line + visible_lines)
        y = body_rect.y
        for line in wrapped_lines[start_line:end_line]:
            rendered = self._small_font.render(line, True, (244, 241, 233))
            self._surface.blit(rendered, (body_rect.x, y))
            y += line_height

        if self._selected_text_max_scroll > 0:
            track_rect = pygame.Rect(panel_rect.right - 16, body_rect.y, 6, body_rect.height)
            pygame.draw.rect(self._surface, (56, 66, 82), track_rect, border_radius=3)
            thumb_height = max(26, int(track_rect.height * (visible_lines / max(len(wrapped_lines), 1))))
            travel = max(0, track_rect.height - thumb_height)
            ratio = self._selected_text_scroll / max(self._selected_text_max_scroll, 1)
            thumb_rect = pygame.Rect(
                track_rect.x,
                track_rect.y + int(travel * ratio),
                track_rect.width,
                thumb_height,
            )
            pygame.draw.rect(self._surface, (233, 198, 132), thumb_rect, border_radius=3)

    def _tooltip_key(self, rect: pygame.Rect, text: str) -> str:
        return f"{rect.x}:{rect.y}:{rect.width}:{rect.height}:{text}"

    def _blit_clamped_line(
        self,
        font: Any,
        text: str,
        position: tuple[int, int],
        color: Color,
        max_width: int,
        *,
        align: str = "left",
        selected: bool = False,
        tooltip_text: str | None = None,
    ) -> pygame.Rect:
        preview, truncated = fit_text(text, font, max_width)
        rendered = font.render(preview or " ", True, color)
        rect = rendered.get_rect()
        if align == "center":
            rect.midtop = position
        elif align == "right":
            rect.topright = position
        else:
            rect.topleft = position
        self._surface.blit(rendered, rect)
        if truncated:
            self._register_tooltip(rect, tooltip_text or text, selected=selected, preferred_width=max(260, max_width))
        return rect

    def _blit_preview_block(
        self,
        font: Any,
        text: str,
        position: tuple[int, int],
        color: Color,
        max_width: int,
        max_lines: int,
        *,
        line_gap: int = 4,
        selected: bool = False,
        tooltip_text: str | None = None,
    ) -> pygame.Rect:
        preview_lines, truncated = preview_wrapped_text(text, font, max_width, max_lines)
        x, y = position
        max_rendered_width = 0
        for line in preview_lines:
            rendered = font.render(line, True, color)
            self._surface.blit(rendered, (x, y))
            max_rendered_width = max(max_rendered_width, rendered.get_width())
            y += rendered.get_height() + line_gap
        rect = pygame.Rect(position[0], position[1], max_rendered_width, max(0, y - position[1] - line_gap))
        if truncated:
            self._register_tooltip(
                rect,
                tooltip_text or text,
                selected=selected,
                preferred_width=max(280, max_width + 24),
            )
        return rect

    def _blit_clamped_lines(
        self,
        lines: list[str],
        font: Any,
        position: tuple[int, int],
        color: Color,
        max_width: int,
        *,
        line_gap: int = 4,
        selected_indices: set[int] | None = None,
    ) -> pygame.Rect:
        x, y = position
        selected_indices = selected_indices or set()
        max_rendered_width = 0
        for index, line in enumerate(lines):
            rect = self._blit_clamped_line(
                font,
                line,
                (x, y),
                color,
                max_width,
                selected=index in selected_indices,
            )
            max_rendered_width = max(max_rendered_width, rect.width)
            y += rect.height + line_gap
        return pygame.Rect(position[0], position[1], max_rendered_width, max(0, y - position[1] - line_gap))


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

    def resolve_player_style(self, gender: str = "male") -> PlaceholderStyle:
        if gender == "female":
            return PlaceholderStyle((183, 111, 146), (91, 45, 68), (255, 245, 232), (46, 16, 12))
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


class Renderer(TooltipMixin):
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
        self._action_targets: list[UiActionTarget] = []
        self._hud_sidebar_targets: list[TooltipTarget] = []
        self._init_tooltip_state()

    def draw(
        self,
        session: GameSessionState,
        mode_label: str,
        elapsed_seconds: float,
        player_label: str,
        story_title: str,
        *,
        player_avatar_gender: str = "male",
        panel_focus: str = "sidebar",
        input_title: str | None = None,
        input_value: str = "",
        input_hint: str = "",
        input_composition: str = "",
        input_cursor: int = 0,
        input_multiline: bool = False,
        input_secret: bool = False,
    ) -> None:
        self._begin_tooltip_frame()
        self._action_targets = []
        self._hud_sidebar_targets = []
        scene = session.current_scene
        self._draw_background(scene)
        self._draw_world(scene, session, elapsed_seconds, player_label, player_avatar_gender)
        active_interactable = session.active_interactable
        options = () if active_interactable is None else session.available_options_for(active_interactable)
        self._draw_game_hud(
            scene,
            session,
            mode_label,
            story_title,
            elapsed_seconds,
            player_label,
            player_avatar_gender,
            active_interactable=active_interactable,
            options=options,
            panel_focus=panel_focus,
        )

        if session.error_message:
            self._draw_error_banner(session.error_message)

        if session.loading:
            self._draw_loading_overlay(session, mode_label)

        if scene.is_terminal and scene.ending_text:
            self._draw_ending_overlay(scene.ending_text)

        if input_title is not None:
            self._draw_input_modal(
                title=input_title,
                value=input_value,
                masked=input_secret,
                hint_text=input_hint,
                composition=input_composition,
                cursor_index=input_cursor,
                multiline=input_multiline,
            )
        else:
            self._draw_tooltip_overlay()
        pygame.display.flip()

    def consume_action_click(self, position: tuple[int, int]) -> str | None:
        for target in reversed(self._action_targets):
            if target.rect.collidepoint(position):
                return target.action
        return None

    def select_hud_sidebar_section(self, index: int) -> bool:
        if not self._hud_sidebar_targets:
            return False
        if index < 0 or index >= len(self._hud_sidebar_targets):
            return False
        self._activate_tooltip_target(self._hud_sidebar_targets[index])
        return True

    def cycle_hud_sidebar_selection(self, delta: int) -> bool:
        if not self._hud_sidebar_targets:
            return False
        selected_index = next(
            (
                index
                for index, target in enumerate(self._hud_sidebar_targets)
                if target.key == self._selected_text_key
            ),
            None,
        )
        if selected_index is None:
            selected_index = 0 if delta >= 0 else len(self._hud_sidebar_targets) - 1
        else:
            selected_index = (selected_index + delta) % len(self._hud_sidebar_targets)
        return self.select_hud_sidebar_section(selected_index)

    def ensure_hud_sidebar_selection(self) -> bool:
        if not self._hud_sidebar_targets:
            return False
        if self.selected_hud_sidebar_index() is not None:
            return True
        return self.select_hud_sidebar_section(0)

    def selected_hud_sidebar_index(self) -> int | None:
        return next(
            (
                index
                for index, target in enumerate(self._hud_sidebar_targets)
                if target.key == self._selected_text_key
            ),
            None,
        )

    def _register_action_target(self, rect: pygame.Rect, action: str) -> None:
        self._action_targets.append(UiActionTarget(rect=rect.copy(), action=action))

    def _draw_background(self, scene: SceneState) -> None:
        background_surface = self._load_scene_background_surface(
            scene.scene.background_image,
            (self._width, self._play_area_height),
            scene.scene.description,
            scene.narrative,
        )
        if background_surface is not None:
            self._surface.blit(background_surface, (0, 0))
            vignette = pygame.Surface((self._width, self._play_area_height), pygame.SRCALPHA)
            vignette.fill((8, 12, 18, 18))
            self._surface.blit(vignette, (0, 0))
            return

        fallback_surface = pygame.Surface((self._width, self._play_area_height))
        fallback_surface.fill((15, 17, 22))
        self._surface.blit(fallback_surface, (0, 0))

    def _load_scene_background_surface(
        self,
        asset_ref: str,
        size: tuple[int, int],
        *hint_texts: str,
    ) -> pygame.Surface | None:
        if self._asset_root == DEFAULT_ASSET_CACHE_ROOT:
            asset_path = resolve_scene_background_path(asset_ref, *hint_texts)
        else:
            asset_path = resolve_cached_asset_path("background", asset_ref, self._asset_root, *hint_texts)
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

    def _draw_world(
        self,
        scene: SceneState,
        session: GameSessionState,
        elapsed_seconds: float,
        player_label: str,
        player_avatar_gender: str,
    ) -> None:
        for npc in scene.npcs:
            self._draw_npc(npc, elapsed_seconds)

        for interactable in scene.interactables:
            if interactable.state.hidden:
                continue
            active = session.active_interactable_id == interactable.id and not session.needs_settlement
            self._draw_interactable(interactable, active)

        self._draw_player(session.player_position, player_label, player_avatar_gender)

    def _draw_npc(self, npc: NPC, elapsed_seconds: float) -> None:
        style = self._resolver.resolve_npc_style(npc.id)
        x, y = self._resolve_npc_position(npc, elapsed_seconds)
        shadow_rect = pygame.Rect(x - 30, y + 58, 60, 18)

        pygame.draw.ellipse(self._surface, style.shadow, shadow_rect)
        sprite = self._load_npc_surface(npc, (132, 132))
        if sprite is not None:
            sprite_rect = sprite.get_rect(midbottom=(x, y + 42))
            self._surface.blit(sprite, sprite_rect)
            self._draw_label(npc.name, (x, sprite_rect.y - 26), style.text, max_width=150)
            return

        body_rect = pygame.Rect(x - 28, y - 72, 56, 108)
        pygame.draw.rect(self._surface, style.fill, body_rect, border_radius=18)
        pygame.draw.rect(self._surface, style.outline, body_rect, width=3, border_radius=18)
        pygame.draw.circle(self._surface, style.fill, (x, y - 92), 24)
        pygame.draw.circle(self._surface, style.outline, (x, y - 92), 24, width=3)
        self._draw_label(npc.name, (x, y - 134), style.text, max_width=150)

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
            self._draw_label(interactable.name, (x, sprite_rect.y - 18), style.text, max_width=150)
            return

        rect = pygame.Rect(x - 28, y - 28, 56, 56)
        pygame.draw.rect(self._surface, style.fill, rect, border_radius=14)
        pygame.draw.rect(self._surface, style.outline, rect, width=3, border_radius=14)
        self._draw_label(interactable.name, (x, y - 44), style.text, max_width=150)

    def _draw_player(
        self,
        player_position: tuple[float, float],
        player_label: str,
        player_avatar_gender: str,
    ) -> None:
        style = self._resolver.resolve_player_style(player_avatar_gender)
        x = int(player_position[0])
        y = int(player_position[1])
        shadow_rect = pygame.Rect(x - 22, y + 24, 44, 14)
        body_rect = pygame.Rect(x - 20, y - 38, 40, 62)

        pygame.draw.ellipse(self._surface, style.shadow, shadow_rect)
        sprite = self._load_player_surface(player_avatar_gender, (102, 146), player_label)
        if sprite is not None:
            sprite_rect = sprite.get_rect(midbottom=(x, y + 28))
            self._surface.blit(sprite, sprite_rect)
            self._draw_label(player_label, (x, sprite_rect.y - 22), style.text, max_width=150)
            return
        pygame.draw.rect(self._surface, style.fill, body_rect, border_radius=14)
        pygame.draw.rect(self._surface, style.outline, body_rect, width=3, border_radius=14)
        pygame.draw.circle(self._surface, style.fill, (x, y - 54), 17)
        pygame.draw.circle(self._surface, style.outline, (x, y - 54), 17, width=3)
        self._draw_label(player_label, (x, y - 86), style.text, max_width=150)

    def _draw_game_hud(
        self,
        scene: SceneState,
        session: GameSessionState,
        mode_label: str,
        story_title: str,
        elapsed_seconds: float,
        player_label: str,
        player_avatar_gender: str,
        *,
        active_interactable: Interactable | None = None,
        options: tuple[ActionOption, ...] = (),
        panel_focus: str = "sidebar",
    ) -> None:
        hud_rect = pygame.Rect(0, self._hud_top, self._width, self._height - self._hud_top)
        overlay = pygame.Surface(hud_rect.size, pygame.SRCALPHA)
        overlay.fill((8, 11, 16, 224))
        self._surface.blit(overlay, hud_rect.topleft)

        top_rect = pygame.Rect(24, 14, self._width - 48, 78)
        top_overlay = pygame.Surface(top_rect.size, pygame.SRCALPHA)
        top_overlay.fill((16, 21, 30, 232))
        self._surface.blit(top_overlay, top_rect.topleft)
        pygame.draw.rect(
            self._surface,
            (242, 210, 168) if panel_focus in {"options", "sidebar"} else (96, 110, 128),
            top_rect,
            width=2,
            border_radius=18,
        )

        clock_x = top_rect.x + 28
        clock_y = top_rect.y + 30
        pygame.draw.circle(self._surface, (229, 233, 239), (clock_x, clock_y), 14, width=2)
        pygame.draw.line(self._surface, (229, 233, 239), (clock_x, clock_y), (clock_x, clock_y - 6), width=2)
        pygame.draw.line(self._surface, (229, 233, 239), (clock_x, clock_y), (clock_x + 6, clock_y + 2), width=2)
        self._blit_clamped_line(
            self._small_font,
            self._format_game_clock(elapsed_seconds),
            (top_rect.x + 52, top_rect.y + 16),
            (248, 239, 227),
            104,
        )
        self._blit_clamped_line(
            self._small_font,
            "鏃跺埢",
            (top_rect.x + 52, top_rect.y + 38),
            (194, 203, 214),
            104,
        )

        center_width = top_rect.width - 340
        self._blit_clamped_line(
            self._title_font,
            story_title,
            (top_rect.centerx, top_rect.y + 8),
            (246, 241, 232),
            center_width,
            align="center",
        )
        self._blit_clamped_line(
            self._small_font,
            scene.scene.description,
            (top_rect.centerx, top_rect.y + 38),
            (214, 220, 230),
            center_width,
            align="center",
        )
        if session.can_force_settle and not session.loading and not scene.is_terminal:
            self._blit_clamped_line(
                self._small_font,
                "T key can advance to the next round.",
                (top_rect.centerx, top_rect.y + 58),
                (238, 199, 132),
                center_width,
                align="center",
            )

        player_rect = pygame.Rect(top_rect.right - 226, top_rect.y + 12, 204, 54)
        player_style = self._resolver.resolve_player_style(player_avatar_gender)
        pygame.draw.circle(self._surface, player_style.fill, (player_rect.x + 18, player_rect.y + 18), 13)
        pygame.draw.circle(self._surface, player_style.outline, (player_rect.x + 18, player_rect.y + 18), 13, width=2)
        self._blit_clamped_line(
            self._small_font,
            player_label,
            (player_rect.x + 40, player_rect.y + 2),
            (248, 241, 230),
            player_rect.width - 44,
        )
        self._blit_clamped_line(
            self._small_font,
            f"鐘舵€?{mode_label}",
            (player_rect.x + 40, player_rect.y + 22),
            (214, 220, 229),
            player_rect.width - 44,
        )
        self._blit_clamped_line(
            self._small_font,
            f"鍦烘櫙 {scene.game_status}",
            (player_rect.x + 40, player_rect.y + 40),
            (179, 188, 199),
            player_rect.width - 44,
        )

        self._draw_action_log_panel(session, panel_focus=panel_focus)
        self._draw_item_panel(
            active_interactable,
            options,
            session,
            panel_focus=panel_focus,
        )

    def _format_game_clock(self, elapsed_seconds: float) -> str:
        base_minutes = 23 * 60 + 30
        minutes = (base_minutes + int(elapsed_seconds // 30)) % (24 * 60)
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _draw_action_log_panel(
        self,
        session: GameSessionState,
        *,
        panel_focus: str = "sidebar",
    ) -> None:
        panel_top = self._height - 176
        panel_height = 154
        margin = 24
        gap = 18
        available_width = self._width - margin * 2 - gap
        log_width = max(380, int(available_width * 0.47))
        item_width = available_width - log_width
        log_rect = pygame.Rect(margin, panel_top, log_width, panel_height)

        log_overlay = pygame.Surface(log_rect.size, pygame.SRCALPHA)
        log_overlay.fill((15, 19, 26, 232))
        self._surface.blit(log_overlay, log_rect.topleft)
        pygame.draw.rect(
            self._surface,
            (242, 210, 168) if panel_focus == "sidebar" else (96, 110, 128),
            log_rect,
            width=2,
            border_radius=18,
        )
        self._blit_clamped_line(
            self._title_font,
            "琛屽姩鏃ュ織",
            (log_rect.x + 16, log_rect.y + 12),
            (245, 236, 222),
            log_rect.width - 32,
        )
        self._blit_clamped_line(
            self._small_font,
            "鏈€杩戝彂鐢熺殑璁板綍",
            (log_rect.right - 16, log_rect.y + 18),
            (184, 192, 202),
            log_rect.width - 32,
            align="right",
        )

        self._hud_sidebar_targets = []
        entries = session.text_history[-3:]
        row_y = log_rect.y + 44
        row_height = 30
        row_gap = 6
        kind_colors: dict[str, tuple[int, int, int]] = {
            "scene": (92, 146, 210),
            "local": (228, 191, 108),
            "system": (170, 181, 192),
            "error": (214, 111, 108),
        }

        if entries:
            for entry in entries:
                row_rect = pygame.Rect(log_rect.x + 14, row_y, log_rect.width - 28, row_height)
                tooltip_text = f"{entry.title}\n{entry.body}"
                is_selected = self._selected_text_key == self._tooltip_key(row_rect, tooltip_text)
                fill_color = kind_colors.get(entry.kind, (88, 96, 108))
                row_overlay = pygame.Surface(row_rect.size, pygame.SRCALPHA)
                row_overlay.fill((*fill_color, 52 if is_selected else 34))
                self._surface.blit(row_overlay, row_rect.topleft)
                pygame.draw.rect(
                    self._surface,
                    (245, 230, 201) if is_selected else (84, 96, 112),
                    row_rect,
                    width=2 if is_selected else 1,
                    border_radius=10,
                )
                pygame.draw.circle(self._surface, fill_color, (row_rect.x + 12, row_rect.y + 15), 4)
                title_preview, _ = fit_text(entry.title, self._small_font, row_rect.width - 28)
                body_preview, _ = fit_text(entry.body.replace("\n", " "), self._small_font, row_rect.width - 28)
                self._surface.blit(
                    self._small_font.render(title_preview or " ", True, (247, 241, 230)),
                    (row_rect.x + 22, row_rect.y + 2),
                )
                self._surface.blit(
                    self._small_font.render(body_preview or " ", True, (210, 217, 226)),
                    (row_rect.x + 22, row_rect.y + 16),
                )

                target = self._register_tooltip(
                    row_rect,
                    tooltip_text,
                    selected=is_selected,
                    preferred_width=540,
                )
                if target is not None:
                    self._hud_sidebar_targets.append(target)
                row_y += row_height + row_gap
        else:
            self._blit_clamped_line(
                self._small_font,
                "鏆傛棤鏃ュ織",
                (log_rect.centerx, log_rect.centery - 4),
                (186, 194, 202),
                log_rect.width - 32,
                align="center",
            )

    def _draw_item_panel(
        self,
        active_interactable: Interactable | None,
        options: tuple[ActionOption, ...],
        session: GameSessionState,
        *,
        panel_focus: str = "options",
    ) -> None:
        panel_top = self._height - 176
        panel_height = 154
        margin = 24
        gap = 18
        available_width = self._width - margin * 2 - gap
        log_width = max(380, int(available_width * 0.47))
        item_width = available_width - log_width
        item_rect = pygame.Rect(margin + log_width + gap, panel_top, item_width, panel_height)

        item_overlay = pygame.Surface(item_rect.size, pygame.SRCALPHA)
        item_overlay.fill((16, 20, 28, 232))
        self._surface.blit(item_overlay, item_rect.topleft)
        pygame.draw.rect(
            self._surface,
            (242, 210, 168) if panel_focus == "options" else (96, 110, 128),
            item_rect,
            width=2,
            border_radius=18,
        )
        self._blit_clamped_line(
            self._title_font,
            "Item bar",
            (item_rect.x + 16, item_rect.y + 12),
            (245, 236, 222),
            item_rect.width - 32,
        )
        self._blit_clamped_line(
            self._small_font,
            "Current available slots.",
            (item_rect.right - 16, item_rect.y + 18),
            (184, 192, 202),
            item_rect.width - 32,
            align="right",
        )

        name_text = active_interactable.name if active_interactable is not None else "Interactable item"
        self._blit_clamped_line(
            self._small_font,
            name_text,
            (item_rect.x + 16, item_rect.y + 42),
            (216, 223, 232),
            item_rect.width - 32,
        )

        slot_top = item_rect.y + 62
        slot_height = 54
        slot_count = 4
        slot_gap = 8
        slot_width = max(76, (item_rect.width - 32 - slot_gap * (slot_count - 1)) // slot_count)
        visible_count = min(slot_count, len(options))
        start_index = 0
        if len(options) > visible_count and visible_count > 0:
            start_index = min(
                max(session.selected_option_index - visible_count // 2, 0),
                len(options) - visible_count,
            )
        visible_options = list(enumerate(options[start_index : start_index + visible_count], start=start_index))

        for slot_index in range(slot_count):
            slot_rect = pygame.Rect(
                item_rect.x + 16 + slot_index * (slot_width + slot_gap),
                slot_top,
                slot_width,
                slot_height,
            )
            option = visible_options[slot_index][1] if slot_index < len(visible_options) else None
            actual_index = visible_options[slot_index][0] if slot_index < len(visible_options) else -1
            if option is not None:
                selected = actual_index == session.selected_option_index
                fill = (232, 194, 126, 62) if selected and panel_focus == "options" else (255, 255, 255, 12)
                border = (247, 224, 164) if selected and panel_focus == "options" else (112, 126, 143)
                self._register_action_target(slot_rect, f"choose_option:{actual_index}")
                resolution_label = "即时AI" if option.resolution_mode == "immediate_ai" else "本地规则"
                text_color = (248, 240, 229) if selected else (231, 235, 241)
                note_color = (244, 215, 157) if selected else (179, 188, 199)
                label = option.label
                note = resolution_label
            else:
                fill = (255, 255, 255, 6)
                border = (83, 93, 106)
                text_color = (154, 164, 176)
                note_color = (125, 135, 146)
                label = "空位"
                note = "等待靠近"

            slot_overlay = pygame.Surface(slot_rect.size, pygame.SRCALPHA)
            slot_overlay.fill(fill)
            self._surface.blit(slot_overlay, slot_rect.topleft)
            pygame.draw.rect(self._surface, border, slot_rect, width=2, border_radius=12)
            self._blit_clamped_line(
                self._body_font,
                f"{slot_index + 1}. {label}",
                (slot_rect.x + 10, slot_rect.y + 8),
                text_color,
                slot_rect.width - 20,
            )
            self._blit_clamped_line(
                self._small_font,
                note,
                (slot_rect.x + 10, slot_rect.y + 32),
                note_color,
                slot_rect.width - 20,
            )

        if len(options) > visible_count:
            self._blit_clamped_line(
                self._small_font,
                f"{start_index + 1}-{start_index + visible_count}/{len(options)}",
                (item_rect.right - 16, item_rect.bottom - 18),
                (184, 192, 202),
                item_rect.width - 32,
                align="right",
            )


    def _draw_input_modal(
        self,
        title: str,
        value: str,
        masked: bool,
        *,
        hint_text: str = "",
        composition: str = "",
        cursor_index: int = 0,
        multiline: bool = False,
    ) -> None:
        overlay = pygame.Surface((self._width, self._height), pygame.SRCALPHA)
        overlay.fill((6, 8, 12, 176))
        self._surface.blit(overlay, (0, 0))

        rect_height = 248 if multiline else 196
        rect = pygame.Rect(236, 208 if multiline else 220, self._width - 472, rect_height)
        pygame.draw.rect(self._surface, (16, 18, 24), rect, border_radius=22)
        pygame.draw.rect(self._surface, (219, 188, 132), rect, width=2, border_radius=22)
        self._blit_clamped_line(
            self._title_font,
            title,
            (rect.x + 24, rect.y + 20),
            (247, 233, 204),
            rect.width - 48,
        )
        self._blit_clamped_line(
            self._small_font,
            "回车确认输入 | Ctrl+V 粘贴 | Esc 取消"
            if not multiline
            else "回车换行 | Ctrl+V 粘贴 | Ctrl+Enter 确认 | Esc 取消",
            (rect.x + 24, rect.y + 56),
            (220, 223, 232),
            rect.width - 48,
        )

        if composition:
            composition_rect = pygame.Rect(rect.x + 22, rect.y + 72, rect.width - 44, 20)
            pygame.draw.rect(self._surface, (69, 52, 30), composition_rect, border_radius=8)
            pygame.draw.rect(self._surface, (235, 202, 140), composition_rect, width=1, border_radius=8)
            self._blit_clamped_line(
                self._small_font,
                f"输入法候选: {composition}",
                (composition_rect.x + 10, composition_rect.y + 2),
                (247, 233, 204),
                composition_rect.width - 20,
            )

        input_rect = pygame.Rect(
            rect.x + 22,
            rect.y + 92,
            rect.width - 44,
            92 if multiline else 52,
        )
        pygame.draw.rect(self._surface, (37, 42, 52), input_rect, border_radius=12)
        pygame.draw.rect(self._surface, (226, 193, 128), input_rect, width=2, border_radius=12)
        display_value = value if not masked else "*" * len(value)
        bounded_cursor = min(max(cursor_index, 0), len(display_value))
        preview_value = f"{display_value[:bounded_cursor]}|{display_value[bounded_cursor:]}"

        if multiline:
            lines = wrap_text(preview_value or " ", self._small_font, input_rect.width - 24)
            y = input_rect.y + 12
            max_height = input_rect.bottom - 10
            for line in lines[:4]:
                rendered = self._small_font.render(line, True, (244, 240, 233))
                self._surface.blit(rendered, (input_rect.x + 12, y))
                y += rendered.get_height() + 6
                if y > max_height:
                    break
        else:
            self._blit_clamped_line(
                self._small_font,
                preview_value or "|",
                (input_rect.x + 12, input_rect.y + 15),
                (244, 240, 233),
                input_rect.width - 24,
            )

        footer_y = input_rect.bottom + 10
        if hint_text:
            self._blit_preview_block(
                self._small_font,
                hint_text,
                (rect.x + 24, footer_y),
                (212, 217, 226),
                rect.width - 48,
                2,
                line_gap=4,
            )

    def _draw_loading_overlay(self, session: GameSessionState, mode_label: str) -> None:
        overlay = pygame.Surface((self._width, self._play_area_height), pygame.SRCALPHA)
        overlay.fill((8, 10, 15, 150))
        self._surface.blit(overlay, (0, 0))

        left_panel = pygame.Rect(72, 84, 320, 340)
        right_panel = pygame.Rect(424, 70, self._width - 496, 372)
        pygame.draw.rect(self._surface, (16, 21, 29), left_panel, border_radius=24)
        pygame.draw.rect(self._surface, (228, 193, 127), left_panel, width=2, border_radius=24)
        pygame.draw.rect(self._surface, (16, 18, 24), right_panel, border_radius=24)
        pygame.draw.rect(self._surface, (118, 132, 156), right_panel, width=2, border_radius=24)

        title_text = (
            "AI is generating the opening scene..."
            if not session.round_actions and not session.settled_action_history
            else "AI is settling the current round..."
        )
        subtitle_text = (
            "The current choice is being resolved and the next scene is warming up."
            if session.round_actions
            else "Loading the opening scene and character state."
        )
        self._draw_loading_spinner((left_panel.centerx, left_panel.y + 92), 42)
        self._blit_clamped_line(
            self._title_font,
            title_text,
            (left_panel.x + 22, left_panel.y + 152),
            (245, 240, 228),
            left_panel.width - 44,
        )
        self._blit_clamped_line(
            self._body_font,
            f"Current mode: {mode_label}",
            (left_panel.x + 24, left_panel.y + 194),
            (219, 224, 234),
            left_panel.width - 48,
        )
        self._blit_preview_block(
            self._small_font,
            subtitle_text,
            (left_panel.x + 24, left_panel.y + 226),
            (228, 211, 182),
            left_panel.width - 48,
            2,
            line_gap=5,
        )

        pending_lines = (
            "\n".join(
                f"{record.turn_index}. {record.label}"
                for record in session.round_actions[-4:]
            )
            if session.round_actions
            else "No pending actions right now."
        )
        self._blit_clamped_line(
            self._small_font,
            "Pending actions",
            (left_panel.x + 24, left_panel.y + 284),
            (242, 226, 188),
            left_panel.width - 48,
        )
        self._blit_preview_block(
            self._small_font,
            pending_lines,
            (left_panel.x + 24, left_panel.y + 308),
            (225, 230, 238),
            left_panel.width - 48,
            4,
            line_gap=4,
            selected=True,
        )

        self._draw_loading_history_panel(session, right_panel)

    def _draw_loading_spinner(self, center: tuple[int, int], radius: int) -> None:
        ticks = pygame.time.get_ticks() / 220
        spinner_surface = pygame.Surface((radius * 2 + 36, radius * 2 + 36), pygame.SRCALPHA)
        spinner_rect = spinner_surface.get_rect(center=center)

        for index in range(10):
            angle = ticks + index * 0.6
            fade = (index + 1) / 10
            dot_radius = int(5 + 5 * fade)
            alpha = int(40 + 200 * fade)
            x = spinner_surface.get_width() / 2 + math.cos(angle) * radius
            y = spinner_surface.get_height() / 2 + math.sin(angle) * radius
            pygame.draw.circle(
                spinner_surface,
                (242, 209, 142, alpha),
                (int(x), int(y)),
                dot_radius,
            )

        pulse_surface = pygame.Surface((spinner_surface.get_width(), spinner_surface.get_height()), pygame.SRCALPHA)
        pulse = 20 + int(8 * math.sin(pygame.time.get_ticks() / 180))
        pygame.draw.circle(
            pulse_surface,
            (245, 229, 198, 36),
            (pulse_surface.get_width() // 2, pulse_surface.get_height() // 2),
            pulse,
            width=3,
        )
        spinner_surface.blit(pulse_surface, (0, 0))
        self._surface.blit(spinner_surface, spinner_rect)

    def _draw_loading_history_panel(self, session: GameSessionState, rect: pygame.Rect) -> None:
        self._blit_clamped_line(
            self._title_font,
            "History",
            (rect.x + 24, rect.y + 18),
            (244, 238, 229),
            rect.width - 48,
        )
        self._blit_clamped_line(
            self._small_font,
            "Review recent scene and system notes while loading.",
            (rect.x + 26, rect.y + 54),
            (213, 217, 226),
            rect.width - 52,
        )

        list_rect = pygame.Rect(rect.x + 20, rect.y + 92, 240, rect.height - 116)
        detail_rect = pygame.Rect(list_rect.right + 18, rect.y + 92, rect.right - list_rect.right - 38, rect.height - 116)
        pygame.draw.rect(self._surface, (24, 31, 42), list_rect, border_radius=18)
        pygame.draw.rect(self._surface, (97, 109, 124), list_rect, width=2, border_radius=18)
        pygame.draw.rect(self._surface, (26, 28, 36), detail_rect, border_radius=18)
        pygame.draw.rect(self._surface, (121, 135, 156), detail_rect, width=2, border_radius=18)

        entries = session.text_history_window(6)
        selected_entry = session.selected_text_history
        selected_index = session.selected_text_history_index

        if not entries or selected_entry is None:
            fallback_body = "\n\n".join(
                [
                    session.premise.simulation_briefing,
                    f"Motivation: {session.premise.motive}",
                    f"Main goal: {session.premise.initial_goal}",
                    f"Hidden goal: {session.premise.hidden_objective}",
                    f"Opening hook: {session.premise.opening_hook}",
                ]
            )
            self._blit_clamped_line(
                self._small_font,
                "Case summary",
                (detail_rect.x + 18, detail_rect.y + 18),
                (243, 228, 194),
                detail_rect.width - 36,
            )
            available_lines = max(6, (detail_rect.height - 64) // (self._small_font.get_height() + 5))
            self._blit_preview_block(
                self._small_font,
                fallback_body,
                (detail_rect.x + 18, detail_rect.y + 50),
                (231, 235, 241),
                detail_rect.width - 36,
                available_lines,
                line_gap=5,
                selected=True,
            )
            return

        row_y = list_rect.y + 16
        for entry_index, entry in entries:
            row_rect = pygame.Rect(list_rect.x + 12, row_y, list_rect.width - 24, 44)
            is_selected = entry_index == selected_index
            fill = (228, 193, 127) if is_selected else (37, 44, 57)
            border = (244, 226, 192) if is_selected else (91, 102, 118)
            text_color = (29, 22, 15) if is_selected else (235, 240, 245)
            badge_color = self._history_kind_color(entry.kind, is_selected)
            pygame.draw.rect(self._surface, fill, row_rect, border_radius=14)
            pygame.draw.rect(self._surface, border, row_rect, width=2, border_radius=14)
            pygame.draw.rect(
                self._surface,
                badge_color,
                pygame.Rect(row_rect.x + 10, row_rect.y + 12, 10, 10),
                border_radius=5,
            )
            self._blit_clamped_line(
                self._small_font,
                entry.title,
                (row_rect.x + 28, row_rect.y + 7),
                text_color,
                row_rect.width - 38,
                selected=is_selected,
            )
            meta_text = (
                f"Turn {entry.turn_index}"
                if entry.turn_index is not None
                else {"scene": "Scene", "local": "Local", "system": "System", "error": "Error"}[entry.kind]
            )
            self._blit_clamped_line(
                self._small_font,
                meta_text,
                (row_rect.x + 28, row_rect.y + 24),
                (76, 56, 32) if is_selected else (178, 188, 202),
                row_rect.width - 38,
                selected=is_selected,
            )
            row_y += 52
            if row_y > list_rect.bottom - 48:
                break

        self._blit_clamped_line(
            self._small_font,
            selected_entry.title,
            (detail_rect.x + 18, detail_rect.y + 18),
            (243, 228, 194),
            detail_rect.width - 36,
            selected=True,
        )
        kind_text = {
            "scene": "Scene narration",
            "local": "Local feedback",
            "system": "System note",
            "error": "Error note",
        }[selected_entry.kind]
        meta_line = (
            f"{kind_text} - Turn {selected_entry.turn_index}"
            if selected_entry.turn_index is not None
            else kind_text
        )
        self._blit_clamped_line(
            self._small_font,
            meta_line,
            (detail_rect.x + 18, detail_rect.y + 46),
            (212, 217, 226),
            detail_rect.width - 36,
            selected=True,
        )
        available_lines = max(6, (detail_rect.height - 100) // (self._small_font.get_height() + 5))
        self._blit_preview_block(
            self._small_font,
            selected_entry.body,
            (detail_rect.x + 18, detail_rect.y + 78),
            (231, 235, 241),
            detail_rect.width - 36,
            available_lines,
            line_gap=5,
            selected=True,
        )

    def _history_kind_color(self, kind: str, selected: bool) -> Color:
        if selected:
            palette = {
                "scene": (116, 82, 35),
                "local": (90, 74, 28),
                "system": (86, 63, 25),
                "error": (121, 54, 42),
            }
        else:
            palette = {
                "scene": (116, 152, 208),
                "local": (209, 179, 101),
                "system": (137, 207, 185),
                "error": (211, 106, 100),
            }
        return palette.get(kind, (180, 180, 180))
    def _draw_ending_overlay(self, ending_text: str) -> None:
        overlay = pygame.Surface((self._width, self._play_area_height), pygame.SRCALPHA)
        overlay.fill((7, 7, 10, 198))
        self._surface.blit(overlay, (0, 0))

        self._blit_clamped_line(
            self._title_font,
            "结局已达成",
            (self._width // 2, 96),
            (245, 236, 220),
            320,
            align="center",
        )
        self._blit_preview_block(
            self._body_font,
            ending_text,
            (self._width // 2 - 360, 150),
            (232, 236, 244),
            720,
            7,
            line_gap=8,
        )
        self._blit_clamped_line(
            self._small_font,
            "按 R 重新开始，按 Esc 返回",
            (self._width // 2, 330),
            (233, 200, 131),
            420,
            align="center",
        )

    def _draw_error_banner(self, message: str) -> None:
        banner_rect = pygame.Rect(24, 18, self._width - 48, 46)
        pygame.draw.rect(self._surface, (134, 34, 30), banner_rect, border_radius=12)
        pygame.draw.rect(self._surface, (255, 196, 184), banner_rect, width=2, border_radius=12)
        self._blit_clamped_line(
            self._small_font,
            message,
            (banner_rect.x + 14, banner_rect.y + 13),
            (255, 242, 236),
            banner_rect.width - 28,
        )

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
                if asset_kind == "background":
                    loaded = pygame.transform.smoothscale(loaded, size)
                else:
                    loaded = _fit_surface_to_box(
                        loaded,
                        size,
                        align_bottom=asset_kind in {"npc", "character"},
                        scale_multiplier=CHARACTER_RENDER_SCALE if asset_kind in {"npc", "character"} else 1.0,
                    )
        except Exception:
            return None

        self._image_cache[cache_key] = loaded
        return loaded

    def _load_player_surface(
        self,
        player_avatar_gender: str,
        size: tuple[int, int],
        *hint_texts: str,
    ) -> pygame.Surface | None:
        for asset_kind, asset_ref in self._player_asset_candidates(player_avatar_gender):
            surface = self._load_asset_surface(asset_kind, asset_ref, size, *hint_texts)
            if surface is not None:
                return surface
        return None

    def _player_asset_candidates(self, player_avatar_gender: str) -> tuple[tuple[str, str], ...]:
        if player_avatar_gender == "female":
            return (
                ("character", "1.png"),
                ("npc", "menu_player_female.png"),
                ("npc", "female_detective.png"),
                ("npc", "female_suspect.png"),
                ("npc", "woman_green.png"),
            )
        return (
            ("character", "2.png"),
            ("npc", "menu_player_male.png"),
            ("npc", "detective.png"),
            ("npc", "man_blue.png"),
            ("npc", "assistant.png"),
        )

    def _load_npc_surface(self, npc: NPC, size: tuple[int, int]) -> pygame.Surface | None:
        for asset_kind, asset_ref in self._npc_asset_candidates(npc):
            surface = self._load_asset_surface(asset_kind, asset_ref, size, npc.id, npc.name, npc.image)
            if surface is not None:
                return surface
        return None

    def _npc_asset_candidates(self, npc: NPC) -> tuple[tuple[str, str], ...]:
        return (
            *self._preferred_character_candidates(npc.id, npc.name, npc.image),
            ("npc", npc.image),
        )

    def _preferred_character_candidates(self, *hint_texts: str) -> tuple[tuple[str, str], ...]:
        specific_candidates = self._specific_character_candidates(*hint_texts)
        if specific_candidates:
            return specific_candidates

        normalized = " ".join(fragment.strip().lower() for fragment in hint_texts if fragment).strip()
        if not normalized:
            return ()

        if self._text_matches_any(normalized, "doctor", "medical", "clinic", "private_doctor", "doctor_zhang"):
            return self._character_asset_sequence("5.png", "6.png", "3.png", "2.png")

        if self._text_matches_any(
            normalized,
            "female",
            "woman",
            "teacher",
            "teacher_lin",
            "su_man",
            "auction_rival",
            "restoration_teacher",
            "zhouyi",
            "ruanzhixia",
            "female_suspect",
            "female_detective",
        ):
            return self._character_asset_sequence("4.png", "1.png", "5.png", "6.png")

        if self._text_matches_any(normalized, "old", "elder", "butler", "guard", "security", "detective", "old_chen", "victim"):
            return self._character_asset_sequence("3.png", "6.png", "2.png", "5.png")

        if self._text_matches_any(normalized, "witness", "man", "male", "polo", "assistant"):
            return self._character_asset_sequence("6.png", "3.png", "2.png", "5.png")

        return self._character_asset_sequence("6.png", "3.png", "4.png", "5.png")

    def _specific_character_candidates(self, *hint_texts: str) -> tuple[tuple[str, str], ...]:
        normalized_hints = {fragment.strip().lower() for fragment in hint_texts if fragment and fragment.strip()}
        if not normalized_hints:
            return ()

        named_sequences: tuple[tuple[set[str], tuple[tuple[str, str], ...]], ...] = (
            ({"old_chen", "victim", "elder", "butler"}, self._character_asset_sequence("3.png", "6.png", "2.png", "5.png")),
            ({"detective", "witness", "guard", "security"}, self._character_asset_sequence("6.png", "3.png", "2.png", "5.png")),
            ({"su_man", "teacher_lin", "chief_caretaker"}, self._character_asset_sequence("4.png", "1.png", "5.png", "6.png")),
            ({"auction_rival", "restoration_teacher", "zhouyi", "ruanzhixia"}, self._character_asset_sequence("4.png", "1.png", "5.png", "6.png")),
            ({"doctor_zhang", "private_doctor"}, self._character_asset_sequence("5.png", "6.png", "3.png", "2.png")),
        )
        for aliases, sequence in named_sequences:
            if normalized_hints & aliases:
                return sequence
        return ()

    def _character_asset_sequence(self, *filenames: str) -> tuple[tuple[str, str], ...]:
        unique: list[tuple[str, str]] = []
        seen: set[str] = set()
        for filename in filenames:
            if filename in seen:
                continue
            seen.add(filename)
            unique.append(("character", filename))
        return tuple(unique)

    def _text_matches_any(self, text: str, *keywords: str) -> bool:
        return any(keyword in text for keyword in keywords)

    def _resolve_npc_position(self, npc: NPC, elapsed_seconds: float) -> tuple[int, int]:
        if not npc.patrol:
            return npc.position

        speed = 78.0
        points = [npc.position, *npc.patrol, npc.position]
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

    def _draw_label(
        self,
        text: str,
        position: tuple[int, int],
        color: Color,
        *,
        max_width: int = 160,
    ) -> None:
        self._blit_clamped_line(
            self._small_font,
            text,
            position,
            color,
            max_width,
            align="center",
        )


def _lerp_color(left: Color, right: Color, ratio: float) -> Color:
    return (
        int(left[0] + (right[0] - left[0]) * ratio),
        int(left[1] + (right[1] - left[1]) * ratio),
        int(left[2] + (right[2] - left[2]) * ratio),
    )


def _tint(color: Color, delta: int) -> Color:
    return tuple(max(0, min(255, channel + delta)) for channel in color)


def _fit_surface_to_box(
    surface: pygame.Surface,
    size: tuple[int, int],
    *,
    align_bottom: bool = False,
    scale_multiplier: float = 1.0,
) -> pygame.Surface:
    target_width, target_height = size
    source_width, source_height = surface.get_size()
    if target_width <= 0 or target_height <= 0 or source_width <= 0 or source_height <= 0:
        return surface

    ratio = min(target_width / source_width, target_height / source_height) * max(scale_multiplier, 0.01)
    scaled_size = (
        max(1, int(round(source_width * ratio))),
        max(1, int(round(source_height * ratio))),
    )
    scaled = pygame.transform.smoothscale(surface, scaled_size)
    canvas = pygame.Surface(size, pygame.SRCALPHA)
    offset_x = (target_width - scaled_size[0]) // 2
    offset_y = target_height - scaled_size[1] if align_bottom else (target_height - scaled_size[1]) // 2
    canvas.blit(scaled, (offset_x, offset_y))
    return canvas


class MenuRenderer(TooltipMixin):
    """Renderer for the main menu, dossier browser, settings and modal overlays."""

    def __init__(
        self,
        surface: pygame.Surface,
        width: int,
        height: int,
        asset_root: Path | None = None,
    ):
        self._surface = surface
        self._width = width
        self._height = height
        self._asset_root = (asset_root or DEFAULT_ASSET_CACHE_ROOT).resolve()
        self._image_cache: dict[tuple[str, tuple[int, int]], pygame.Surface] = {}
        self._display_font = pygame.font.SysFont("georgia", 46, bold=True)
        self._hero_font = pygame.font.SysFont("georgia", 72, bold=True)
        self._title_font = pygame.font.SysFont("microsoftyaheiui", 28, bold=True)
        self._body_font = pygame.font.SysFont("microsoftyaheiui", 20)
        self._small_font = pygame.font.SysFont("microsoftyaheiui", 15)
        self._main_menu_targets: list[UiActionTarget] = []
        self._profile_setup_targets: list[UiActionTarget] = []
        self._init_tooltip_state()

    def _load_menu_art_surface(self, asset_path: str, size: tuple[int, int]) -> pygame.Surface | None:
        return self._load_menu_asset_surface("background", asset_path, size, "menu")

    def _scale_menu_rect(self, rect: tuple[int, int, int, int]) -> pygame.Rect:
        source_width = 2281
        source_height = 1280
        x, y, width, height = rect
        return pygame.Rect(
            round(x * self._width / source_width),
            round(y * self._height / source_height),
            max(1, round(width * self._width / source_width)),
            max(1, round(height * self._height / source_height)),
        )

    def _main_menu_button_rects(self) -> tuple[pygame.Rect, ...]:
        return (
            self._scale_menu_rect((918, 492, 442, 100)),
            self._scale_menu_rect((918, 640, 442, 100)),
            self._scale_menu_rect((918, 795, 442, 101)),
            self._scale_menu_rect((918, 949, 442, 104)),
        )

    def _profile_setup_input_rect(self) -> pygame.Rect:
        return self._scale_menu_rect((1264, 384, 509, 120))

    def _profile_setup_gender_rects(self) -> tuple[pygame.Rect, pygame.Rect]:
        return (
            self._scale_menu_rect((1260, 627, 216, 118)),
            self._scale_menu_rect((1538, 627, 216, 118)),
        )

    def _profile_setup_start_rect(self) -> pygame.Rect:
        return self._scale_menu_rect((1367, 828, 424, 124))

    def _draw_main_menu_art_overlay(
        self,
        options: list[str],
        selected_index: int,
        status_text: str | None,
    ) -> None:
        button_rects = self._main_menu_button_rects()
        self._main_menu_targets = []

        action_by_index = {
            0: "start_game",
            1: "custom_story",
            2: "settings",
            3: "exit_game",
        }

        for index, (option, button_rect) in enumerate(zip(options, button_rects)):
            action = action_by_index.get(index, "start_game")
            self._main_menu_targets.append(UiActionTarget(rect=button_rect.copy(), action=action))
            self._register_tooltip(
                button_rect,
                option,
                selected=index == selected_index,
                preferred_width=max(280, button_rect.width),
            )
            if index == selected_index:
                highlight = pygame.Surface(button_rect.size, pygame.SRCALPHA)
                highlight.fill((255, 214, 136, 38))
                self._surface.blit(highlight, button_rect.topleft)
                pygame.draw.rect(self._surface, (244, 214, 148), button_rect, width=3, border_radius=18)

        if status_text:
            self._blit_clamped_line(
                self._small_font,
                status_text,
                (self._width // 2, self._height - 26),
                (244, 223, 178),
                self._width - 80,
                align="center",
            )

    def _draw_profile_setup_overlay(
        self,
        draft: Any,
        editing_field: str | None,
        input_buffer: str,
        *,
        input_hint: str = "",
        input_composition: str = "",
        input_cursor: int = 0,
        input_secret: bool = False,
        status_text: str | None = None,
    ) -> None:
        self._profile_setup_targets = []

        input_rect = self._profile_setup_input_rect()
        male_rect, female_rect = self._profile_setup_gender_rects()
        start_rect = self._profile_setup_start_rect()

        current_gender = str(getattr(draft, "avatar_gender", "male")).strip().lower()
        current_name = str(getattr(draft, "detective_name", "")).strip()
        display_value = input_buffer if not input_secret else "*" * len(input_buffer)
        if editing_field == "profile_detective_name":
            cursor = min(max(input_cursor, 0), len(display_value))
            display_value = f"{display_value[:cursor]}|{display_value[cursor:]}" if display_value else "|"
        elif not display_value:
            display_value = current_name or "请点击输入框"

        self._blit_clamped_line(
            self._body_font,
            display_value,
            (input_rect.x + 18, input_rect.y + 36),
            (238, 242, 248),
            input_rect.width - 36,
        )
        if input_composition:
            self._blit_clamped_line(
                self._small_font,
                f"输入法候选: {input_composition}",
                (input_rect.x + 18, input_rect.bottom + 8),
                (230, 210, 167),
                input_rect.width - 36,
            )
        elif input_hint:
            self._blit_clamped_line(
                self._small_font,
                input_hint,
                (input_rect.x + 18, input_rect.bottom + 8),
                (230, 210, 167),
                input_rect.width - 36,
            )

        gender_targets = (
            ("gender_male", male_rect, "?", current_gender == "male"),
            ("gender_female", female_rect, "?", current_gender == "female"),
        )
        for action, rect, label, selected in gender_targets:
            self._profile_setup_targets.append(UiActionTarget(rect=rect.copy(), action=action))
            fill = (255, 227, 161, 34) if selected else (255, 255, 255, 10)
            overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
            overlay.fill(fill)
            self._surface.blit(overlay, rect.topleft)
            border_color = (247, 222, 154) if selected else (161, 192, 214)
            pygame.draw.rect(self._surface, border_color, rect, width=3 if selected else 2, border_radius=10)
            self._blit_clamped_line(
                self._title_font,
                label,
                rect.center,
                (244, 232, 214) if selected else (220, 226, 234),
                rect.width - 26,
                align="center",
            )

        self._profile_setup_targets.append(UiActionTarget(rect=input_rect.copy(), action="edit_id"))
        self._profile_setup_targets.append(UiActionTarget(rect=start_rect.copy(), action="start_game"))

        if editing_field == "profile_detective_name":
            pygame.draw.rect(self._surface, (244, 214, 148), input_rect, width=3, border_radius=8)
        else:
            pygame.draw.rect(self._surface, (166, 187, 206), input_rect, width=2, border_radius=8)

        start_fill = (255, 227, 161, 28) if current_name else (255, 255, 255, 8)
        start_overlay = pygame.Surface(start_rect.size, pygame.SRCALPHA)
        start_overlay.fill(start_fill)
        self._surface.blit(start_overlay, start_rect.topleft)
        pygame.draw.rect(self._surface, (247, 222, 154), start_rect, width=2, border_radius=10)
        self._blit_clamped_line(
            self._title_font,
            "开始游戏",
            start_rect.center,
            (245, 233, 219),
            start_rect.width - 32,
            align="center",
        )

        if status_text:
            self._blit_clamped_line(
                self._small_font,
                status_text,
                (self._width // 2, self._height - 30),
                (244, 223, 178),
                self._width - 80,
                align="center",
            )

    def _menu_player_showcase_rect(self) -> pygame.Rect:
        showcase_width = min(212, max(164, self._width // 6))
        showcase_height = max(420, self._height - 172)
        return pygame.Rect(24, 120, showcase_width, showcase_height)

    def _menu_content_rect(self) -> pygame.Rect:
        showcase_rect = self._menu_player_showcase_rect()
        content_left = showcase_rect.right + 28
        return pygame.Rect(
            content_left,
            0,
            max(520, self._width - content_left - 48),
            self._height,
        )

    def _split_menu_columns(
        self,
        content_rect: pygame.Rect,
        *,
        left_ratio: float,
        gap: int = 24,
        min_left: int = 340,
        min_right: int = 400,
        y: int,
        height: int,
    ) -> tuple[pygame.Rect, pygame.Rect]:
        available_width = max(0, content_rect.width - gap)
        left_width = max(min_left, int(available_width * left_ratio))
        left_width = min(left_width, max(min_left, available_width - min_right))
        right_width = max(min_right, available_width - left_width)
        if left_width + right_width > available_width:
            left_width = max(min_left, available_width - min_right)
            right_width = max(min_right, available_width - left_width)

        left_rect = pygame.Rect(content_rect.x, y, left_width, height)
        right_rect = pygame.Rect(left_rect.right + gap, y, right_width, height)
        return left_rect, right_rect

    def draw_main_menu(
        self,
        *args: Any,
        options: list[str] | None = None,
        status_text: str | None = None,
        operator_portrait_name: str | None = None,
        operator_portrait_gender: str = "male",
    ) -> None:
        self._begin_tooltip_frame()
        background_surface = self._load_menu_art_surface(MAIN_MENU_ART_PATH, (self._width, self._height))
        if background_surface is not None:
            self._surface.blit(background_surface, (0, 0))
        else:
            self._draw_background(menu_kind="main_menu")

        selected_index = 0
        if args:
            if isinstance(args[0], int):
                selected_index = args[0]
                if len(args) > 1:
                    status_text = args[1]
                if options is None and len(args) > 2 and isinstance(args[2], (list, tuple)):
                    options = list(args[2])
            else:
                if len(args) >= 3:
                    _, legacy_options, legacy_selected_index = args[:3]
                    if options is None and isinstance(legacy_options, (list, tuple)):
                        options = list(legacy_options)
                    if isinstance(legacy_selected_index, int):
                        selected_index = legacy_selected_index
                    if len(args) > 3:
                        status_text = args[3]

        option_labels = options or ["开始游戏", "自定义剧本", "选项设置", "退出游戏"]
        self._draw_main_menu_art_overlay(option_labels, selected_index, status_text)
        self._draw_tooltip_overlay()
        pygame.display.flip()

    def draw_profile_setup(
        self,
        draft: Any,
        editing_field: str | None,
        input_buffer: str,
        status_text: str | None,
        *,
        input_hint: str = "",
        input_composition: str = "",
        input_cursor: int = 0,
        input_secret: bool = False,
    ) -> None:
        self._begin_tooltip_frame()
        background_surface = self._load_menu_art_surface(PROFILE_SETUP_ART_PATH, (self._width, self._height))
        if background_surface is not None:
            self._surface.blit(background_surface, (0, 0))
        else:
            self._draw_background(menu_kind="main_menu")

        self._draw_profile_setup_overlay(
            draft,
            editing_field,
            input_buffer,
            input_hint=input_hint,
            input_composition=input_composition,
            input_cursor=input_cursor,
            input_secret=input_secret,
            status_text=status_text,
        )
        self._draw_tooltip_overlay()
        pygame.display.flip()

    def consume_main_menu_action(self, position: tuple[int, int]) -> str | None:
        for target in reversed(self._main_menu_targets):
            if target.rect.collidepoint(position):
                return target.action
        return None

    def consume_profile_setup_action(self, position: tuple[int, int]) -> str | None:
        for target in reversed(self._profile_setup_targets):
            if target.rect.collidepoint(position):
                return target.action
        return None

    def draw_story_browser(
        self,
        background: Any,
        story: Any,
        role: Any,
        story_index: int,
        story_count: int,
        focus: str,
        detail_modal: Any | None,
        *,
        operator_portrait_name: str | None = None,
        operator_portrait_gender: str = "male",
    ) -> None:
        self._begin_tooltip_frame()
        self._draw_background(
            menu_kind="story_browser",
            operator_portrait_name=operator_portrait_name,
            operator_portrait_gender=operator_portrait_gender,
        )
        self._draw_chrome(background.game_title, "卷宗选择", background.operator_name)

        content_rect = self._menu_content_rect()
        left, right = self._split_menu_columns(
            content_rect,
            left_ratio=0.44,
            min_left=400,
            min_right=450,
            y=126,
            height=520,
        )
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
        self._blit_clamped_line(
            self._small_font,
            f"评级: {ranking_text}",
            (left.x + 24, left.bottom - 40),
            (203, 210, 220),
            left.width - 48,
            selected=focus == "story",
        )

        self._section_title("角色概览", right.x + 22, right.y + 18)
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

        footer = "卷宗页控制: 左右切换卷宗 | 上下切换角色 | Tab 切换焦点 | Enter 查看详情 | Space 开始案件 | Backspace 返回"
        self._draw_footer(footer, None)
        if detail_modal is not None:
            self._draw_detail_modal(detail_modal)
        self._draw_tooltip_overlay()
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
        *,
        input_hint: str = "",
        input_composition: str = "",
        input_cursor: int = 0,
        input_multiline: bool = False,
        input_secret: bool = False,
        operator_portrait_name: str | None = None,
        operator_portrait_gender: str = "male",
    ) -> None:
        self._begin_tooltip_frame()
        self._draw_background(
            menu_kind="settings",
            operator_portrait_name=operator_portrait_name,
            operator_portrait_gender=operator_portrait_gender,
        )
        self._draw_chrome(background.game_title, "选项设置", background.operator_name)

        content_rect = self._menu_content_rect()
        panel = pygame.Rect(content_rect.x, 126, content_rect.width, 520)
        self._panel(panel, (16, 21, 28))
        self._section_title("运行与 AI 请求设置", panel.x + 24, panel.y + 18)

        self._blit_clamped_line(
            self._small_font,
            "包含 AI 请求地址、API Key、模型、回退策略以及基础显示设置。选中后按 Enter 编辑，布尔项可直接切换。",
            (panel.x + 24, panel.y + 58),
            (219, 224, 231),
            panel.width - 48,
        )

        column_count = 2 if panel.width >= 880 else 1
        column_gap = 18
        rows_per_column = max(1, math.ceil(len(fields) / column_count))
        available_width = panel.width - 48 - column_gap * (column_count - 1)
        column_width = max(280, available_width // column_count)
        row_height = 36
        row_gap = 8

        for index, (field_name, label, field_kind) in enumerate(fields):
            column_index = index // rows_per_column
            row_index = index % rows_per_column
            row = pygame.Rect(
                panel.x + 24 + column_index * (column_width + column_gap),
                panel.y + 96 + row_index * (row_height + row_gap),
                column_width,
                row_height,
            )
            selected = index == selected_index
            fill = (228, 193, 127) if selected else (34, 41, 52)
            border = (244, 227, 192) if selected else (97, 109, 123)
            text_color = (28, 22, 15) if selected else (236, 240, 245)
            pygame.draw.rect(self._surface, fill, row, border_radius=12)
            pygame.draw.rect(self._surface, border, row, width=2, border_radius=12)

            full_value = self._format_setting_value(field_name, field_kind, draft)
            self._blit_clamped_line(
                self._small_font,
                label,
                (row.x + 14, row.y + 8),
                text_color,
                max(120, row.width // 2 - 18),
                selected=selected,
            )
            self._blit_clamped_line(
                self._small_font,
                full_value,
                (row.x + row.width // 2, row.y + 11),
                text_color,
                max(120, row.width // 2 - 18),
                selected=selected,
                tooltip_text=f"{label}: {full_value}",
            )

        tips = [
            "必要设置:",
            "1. 请求 URL / Base URL",
            "2. API Key",
            "3. 模型名与回退策略",
            "4. Tab 切换字段",
        ]
        self._blit_clamped_lines(
            tips,
            self._small_font,
            (panel.x + 24, panel.bottom - 112),
            (230, 210, 167),
            panel.width - 48,
            line_gap=5,
        )
        footer = "设置页控制: 上下切换 | Enter 编辑/切换 | 左右切换布尔值 | S 保存 | D 放弃修改 | Backspace 返回"
        self._draw_footer(footer, status_text)

        if editing_field is not None:
            self._draw_input_modal(
                title=self._field_label(editing_field, fields),
                value=input_buffer,
                masked=input_secret,
                hint_text=input_hint,
                composition=input_composition,
                cursor_index=input_cursor,
                multiline=input_multiline,
            )
        self._draw_tooltip_overlay()
        pygame.display.flip()

    def draw_custom_story_editor(
        self,
        background: Any,
        fields: list[Any],
        selected_index: int,
        draft: Any,
        editing_field: str | None,
        input_buffer: str,
        status_text: str | None,
        *,
        generated_story_id: str,
        input_hint: str = "",
        input_composition: str = "",
        input_cursor: int = 0,
        input_multiline: bool = False,
        input_secret: bool = False,
        operator_portrait_name: str | None = None,
        operator_portrait_gender: str = "male",
    ) -> None:
        self._begin_tooltip_frame()
        self._draw_background(
            menu_kind="custom_story",
            operator_portrait_name=operator_portrait_name,
            operator_portrait_gender=operator_portrait_gender,
        )
        self._draw_chrome(background.game_title, "Custom Story Editor", background.operator_name)

        content_rect = self._menu_content_rect()
        left, right = self._split_menu_columns(
            content_rect,
            left_ratio=0.48,
            min_left=430,
            min_right=420,
            y=126,
            height=520,
        )
        self._panel(left, (16, 21, 28))
        self._panel(right, (27, 22, 19))

        self._section_title("Story Fields", left.x + 22, left.y + 18)
        self._blit_clamped_line(
            self._small_font,
            "Edit the custom story fields and preview the generated result.",
            (left.x + 24, left.y + 56),
            (219, 224, 231),
            left.width - 48,
        )

        row_height = 36
        row_gap = 8
        visible_rows = 10
        window_start = 0
        if len(fields) > visible_rows:
            window_start = max(0, min(selected_index - visible_rows // 2, len(fields) - visible_rows))
        visible_fields = fields[window_start : window_start + visible_rows]

        for offset, field in enumerate(visible_fields):
            index = window_start + offset
            row = pygame.Rect(
                left.x + 22,
                left.y + 96 + offset * (row_height + row_gap),
                left.width - 44,
                row_height,
            )
            selected = index == selected_index
            kind = getattr(field, "kind", "text")
            if kind == "action":
                fill = (194, 130, 92) if selected else (66, 48, 44)
                border = (245, 220, 194) if selected else (145, 110, 100)
                text_color = (25, 18, 14) if selected else (242, 234, 228)
            elif kind == "readonly":
                fill = (96, 111, 132) if selected else (41, 49, 60)
                border = (220, 233, 247) if selected else (97, 109, 123)
                text_color = (18, 22, 27) if selected else (236, 240, 245)
            else:
                fill = (228, 193, 127) if selected else (34, 41, 52)
                border = (244, 227, 192) if selected else (97, 109, 123)
                text_color = (28, 22, 15) if selected else (236, 240, 245)
            pygame.draw.rect(self._surface, fill, row, border_radius=12)
            pygame.draw.rect(self._surface, border, row, width=2, border_radius=12)

            raw_value = str(getattr(field, "value", "")).strip()
            full_value = raw_value if raw_value else "(empty)"
            if kind == "multiline":
                compact_value = " / ".join(part.strip() for part in raw_value.splitlines() if part.strip())
                display_value = compact_value or "(empty)"
            else:
                display_value = full_value

            self._blit_clamped_line(
                self._small_font,
                getattr(field, "label", ""),
                (row.x + 14, row.y + 8),
                text_color,
                160,
                selected=selected,
            )
            self._blit_clamped_line(
                self._small_font,
                display_value,
                (row.x + 176, row.y + 8),
                text_color,
                row.width - 192,
                selected=selected,
                tooltip_text=f"{getattr(field, "label", "")}: {full_value}",
            )
            self._register_tooltip(
                row,
                f"{getattr(field, "label", "")}\n{full_value}",
                selected=selected,
                preferred_width=max(340, row.width),
            )

        self._blit_clamped_line(
            self._small_font,
            f"{selected_index + 1}/{max(len(fields), 1)}",
            (left.right - 18, left.y + 20),
            (228, 194, 131),
            120,
            align="right",
        )

        self._section_title("Story Preview", right.x + 22, right.y + 18)
        self._blit_clamped_line(
            self._small_font,
            f"Generated story id: {generated_story_id}",
            (right.x + 24, right.y + 56),
            (228, 194, 131),
            right.width - 48,
        )

        preview_card = pygame.Rect(right.x + 22, right.y + 88, right.width - 44, 348)
        pygame.draw.rect(self._surface, (33, 37, 46), preview_card, border_radius=18)
        pygame.draw.rect(self._surface, (120, 106, 92), preview_card, width=2, border_radius=18)

        story_title = str(getattr(draft, "title", "")).strip() or "Untitled Story"
        story_subtitle = str(getattr(draft, "subtitle", "")).strip() or "Story draft"
        self._blit_clamped_line(
            self._title_font,
            story_title,
            (preview_card.x + 18, preview_card.y + 16),
            (244, 240, 233),
            preview_card.width - 36,
        )
        self._blit_clamped_line(
            self._small_font,
            story_subtitle,
            (preview_card.x + 18, preview_card.y + 52),
            (228, 194, 131),
            preview_card.width - 36,
        )

        preview_blocks = [
            f"Location: {str(getattr(draft, 'location', '')).strip() or '(empty)'}",
            f"Victim: {str(getattr(draft, 'victim_name', '')).strip() or '(empty)'} / {str(getattr(draft, 'victim_identity', '')).strip() or '(empty)'}",
            str(getattr(draft, 'setting', '')).strip() or "Setting pending.",
            str(getattr(draft, 'core_case', '')).strip() or "Core case pending.",
            str(getattr(draft, 'opening_hook', '')).strip() or "Opening hook pending.",
        ]
        y = preview_card.y + 88
        for block in preview_blocks:
            block_rect = self._blit_preview_block(
                self._small_font,
                block,
                (preview_card.x + 18, y),
                (225, 229, 235),
                preview_card.width - 36,
                4,
                line_gap=4,
            )
            y += block_rect.height + 12
            if y > preview_card.bottom - 48:
                break

        role_preview_title_y = preview_card.bottom + 14
        self._blit_clamped_line(
            self._small_font,
            "Role Preview",
            (right.x + 24, role_preview_title_y),
            (243, 228, 194),
            right.width - 48,
        )
        role_preview_body = "This panel shows the current role summary, tools, and strategy."
        draft_roles = list(getattr(draft, "roles", []))
        if draft_roles:
            preview_lines: list[str] = []
            for role in draft_roles[:3]:
                role_name = str(getattr(role, "name", "")).strip() or str(getattr(role, "title", "")).strip() or "Role"
                tools = [
                    str(getattr(tool, "name", "")).strip()
                    for tool in getattr(role, "signature_tools", [])
                    if str(getattr(tool, "name", "")).strip()
                ]
                tool_text = " / ".join(tools[:2]) if tools else "No tools yet"
                preview_lines.append(
                    f"{role_name} / {str(getattr(role, "strategy_kind", "")).strip() or "facility"} / {tool_text}"
                )
            if len(draft_roles) > 3:
                preview_lines.append(f"... and {len(draft_roles) - 3} more roles")
            role_preview_body = "\n".join(preview_lines)
        self._blit_preview_block(
            self._small_font,
            role_preview_body,
            (right.x + 24, role_preview_title_y + 28),
            (225, 229, 235),
            right.width - 48,
            5,
            line_gap=5,
        )

        tips = [
            "Enter: edit the selected field",
            "Delete: clear the selected field",
            "Tab: switch focus",
            "Backspace: delete the last character",
        ]
        self._blit_clamped_lines(
            tips,
            self._small_font,
            (right.x + 24, right.y + 470),
            (230, 210, 167),
            right.width - 48,
            line_gap=5,
        )
        footer = "Enter confirm | Delete clear | Tab switch | Backspace delete"
        self._draw_footer(footer, status_text)

        if editing_field is not None:
            self._draw_input_modal(
                title=self._field_label(editing_field, fields),
                value=input_buffer,
                masked=input_secret,
                hint_text=input_hint,
                composition=input_composition,
                cursor_index=input_cursor,
                multiline=input_multiline,
            )
        self._draw_tooltip_overlay()
        pygame.display.flip()

    def _draw_background(
        self,
        *,
        menu_kind: str = "main_menu",
        operator_portrait_name: str | None = None,
        operator_portrait_gender: str = "male",
    ) -> None:
        background_surface = self._load_menu_background_surface(menu_kind, (self._width, self._height))
        if background_surface is not None:
            self._surface.blit(background_surface, (0, 0))
            shade = pygame.Surface((self._width, self._height), pygame.SRCALPHA)
            shade.fill((7, 11, 16, 176))
            self._surface.blit(shade, (0, 0))
        else:
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

        vignette = pygame.Surface((self._width, self._height), pygame.SRCALPHA)
        pygame.draw.rect(vignette, (0, 0, 0, 90), vignette.get_rect(), width=52, border_radius=24)
        self._surface.blit(vignette, (0, 0))

        self._draw_detective_ui_stamp()
        self._draw_operator_portrait_backdrop(operator_portrait_name, operator_portrait_gender)

    def _draw_operator_portrait_backdrop(
        self,
        operator_portrait_name: str | None,
        operator_portrait_gender: str,
    ) -> None:
        showcase_rect = self._menu_player_showcase_rect()
        glow_rect = showcase_rect.inflate(30, 34)
        glow_surface = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
        pygame.draw.ellipse(
            glow_surface,
            (225, 194, 131, 34),
            glow_surface.get_rect(),
        )
        self._surface.blit(glow_surface, glow_rect.topleft)

        frame_surface = pygame.Surface(showcase_rect.size, pygame.SRCALPHA)
        pygame.draw.rect(frame_surface, (10, 15, 21, 214), frame_surface.get_rect(), border_radius=28)
        pygame.draw.rect(frame_surface, (201, 169, 111, 126), frame_surface.get_rect(), width=2, border_radius=28)
        self._surface.blit(frame_surface, showcase_rect.topleft)

        portrait_rect = pygame.Rect(
            showcase_rect.x + 12,
            showcase_rect.y + 14,
            showcase_rect.width - 24,
            showcase_rect.height - 108,
        )
        portrait_surface = self._load_menu_portrait_surface(
            operator_portrait_gender,
            portrait_rect.size,
            operator_portrait_name or "",
        )
        if portrait_surface is not None:
            toned = portrait_surface.copy()
            shade = pygame.Surface(toned.get_size(), pygame.SRCALPHA)
            shade.fill((8, 12, 18, 62))
            toned.blit(shade, (0, 0))
            toned.set_alpha(244)
            self._surface.blit(toned, portrait_rect.topleft)
        else:
            self._draw_portrait_placeholder(portrait_rect, operator_portrait_gender)

        label_surface = pygame.Surface((showcase_rect.width - 24, 84), pygame.SRCALPHA)
        pygame.draw.rect(label_surface, (8, 12, 18, 172), label_surface.get_rect(), border_radius=18)
        label_rect = label_surface.get_rect(midbottom=(showcase_rect.centerx, showcase_rect.bottom - 16))
        self._surface.blit(label_surface, label_rect)

        self._blit_clamped_line(
            self._small_font,
            "涓绘帶妗ｆ",
            (label_rect.x + 14, label_rect.y + 12),
            (241, 226, 194),
            label_rect.width - 28,
        )
        portrait_label = operator_portrait_name or (
            "Female lead" if operator_portrait_gender == "female" else "Male lead"
        )
        self._blit_clamped_line(
            self._small_font,
            portrait_label,
            (label_rect.x + 14, label_rect.y + 38),
            (217, 222, 230),
            label_rect.width - 28,
        )

    def _draw_portrait_placeholder(self, portrait_rect: pygame.Rect, operator_portrait_gender: str) -> None:
        silhouette = pygame.Surface(portrait_rect.size, pygame.SRCALPHA)
        tint = (207, 154, 171, 74) if operator_portrait_gender == "female" else (188, 170, 149, 74)
        outline = (232, 204, 160, 52)
        center_x = portrait_rect.width // 2
        body_top = max(92, portrait_rect.height // 3)
        body_bottom = portrait_rect.height - 26
        head_radius = max(30, portrait_rect.width // 9)

        pygame.draw.ellipse(
            silhouette,
            (12, 16, 22, 88),
            pygame.Rect(center_x - 92, body_bottom - 34, 184, 34),
        )
        pygame.draw.circle(silhouette, tint, (center_x, body_top - 28), head_radius)
        pygame.draw.polygon(
            silhouette,
            tint,
            [
                (center_x - 72, body_top + 12),
                (center_x + 72, body_top + 12),
                (center_x + 122, body_bottom),
                (center_x - 122, body_bottom),
            ],
        )
        pygame.draw.circle(silhouette, outline, (center_x, body_top - 28), head_radius, width=4)
        pygame.draw.polygon(
            silhouette,
            outline,
            [
                (center_x - 72, body_top + 12),
                (center_x + 72, body_top + 12),
                (center_x + 122, body_bottom),
                (center_x - 122, body_bottom),
            ],
            width=4,
        )
        self._surface.blit(silhouette, portrait_rect.topleft)

    def _load_menu_portrait_surface(
        self,
        operator_portrait_gender: str,
        size: tuple[int, int],
        *hint_texts: str,
    ) -> pygame.Surface | None:
        for asset_kind, asset_ref in self._menu_portrait_candidates(operator_portrait_gender):
            surface = self._load_menu_asset_surface(asset_kind, asset_ref, size, *hint_texts)
            if surface is not None:
                return surface
        return None

    def _menu_portrait_candidates(self, operator_portrait_gender: str) -> tuple[tuple[str, str], ...]:
        if operator_portrait_gender == "female":
            return (
                ("character", "1.png"),
                ("npc", "menu_player_female.png"),
                ("npc", "female_detective.png"),
                ("npc", "female_suspect.png"),
                ("npc", "woman_green.png"),
            )
        return (
            ("character", "2.png"),
            ("npc", "menu_player_male.png"),
            ("npc", "detective.png"),
            ("npc", "man_blue.png"),
            ("npc", "assistant.png"),
        )

    def _load_menu_asset_surface(
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
                if asset_kind == "background":
                    loaded = pygame.transform.smoothscale(loaded, size)
                else:
                    loaded = _fit_surface_to_box(
                        loaded,
                        size,
                        align_bottom=asset_kind in {"npc", "character"},
                        scale_multiplier=CHARACTER_RENDER_SCALE if asset_kind in {"npc", "character"} else 1.0,
                    )
        except Exception:
            return None

        self._image_cache[cache_key] = loaded
        return loaded

    def _load_menu_background_surface(
        self,
        menu_kind: str,
        size: tuple[int, int],
    ) -> pygame.Surface | None:
        for asset_ref in self._menu_background_candidates(menu_kind):
            surface = self._load_menu_asset_surface("background", asset_ref, size, menu_kind)
            if surface is not None:
                return surface
        return None

    def _menu_background_candidates(self, menu_kind: str) -> tuple[str, ...]:
        if menu_kind == "story_browser":
            return (
                "cybernoir_loft_lounge.png",
                "menu_cybernoir_cover_4.png",
                "menu_cybernoir_cover_3.png",
                "front_gallery.png",
            )
        if menu_kind == "settings":
            return (
                "cybernoir_loft_lounge.png",
                "menu_cybernoir_cover_5.png",
                "security_control_room.png",
                "menu_cybernoir_cover_4.png",
            )
        if menu_kind == "custom_story":
            return (
                "cybernoir_loft_lounge.png",
                "menu_cybernoir_cover_3.png",
                "menu_cybernoir_cover_5.png",
                "mansion_study_room.png",
            )
        return (
            "cybernoir_loft_lounge.png",
            "menu_cybernoir_cover_3.png",
            "menu_cybernoir_cover_4.png",
            "menu_cybernoir_cover_5.png",
        )

    def _draw_detective_ui_stamp(self) -> None:
        stamp_size = min(132, max(92, self._width // 12))
        stamp = self._load_menu_asset_surface(
            "ui",
            "detective_handdrawn_demo.png",
            (stamp_size, stamp_size),
            "detective",
            "ui",
            "stamp",
        )
        if stamp is None:
            return

        toned = stamp.copy()
        shade = pygame.Surface(toned.get_size(), pygame.SRCALPHA)
        shade.fill((8, 12, 18, 176))
        toned.blit(shade, (0, 0))
        toned.set_alpha(136)
        stamp_rect = toned.get_rect(topleft=(34, self._height - stamp_size - 92))
        self._surface.blit(toned, stamp_rect)

    def _draw_chrome(self, title_text: str, subtitle_text: str, operator_name: str) -> None:
        header_rect = pygame.Rect(34, 24, self._width - 68, 84)
        pygame.draw.rect(self._surface, (19, 24, 33), header_rect, border_radius=20)
        pygame.draw.rect(self._surface, (201, 169, 111), header_rect, width=2, border_radius=20)

        badge_rect = pygame.Rect(self._width - 208, 42, 154, 34)
        pygame.draw.rect(self._surface, (228, 194, 131), badge_rect, border_radius=12)
        self._blit_clamped_line(
            self._display_font,
            title_text,
            (58, 34),
            (244, 232, 207),
            header_rect.width - 250,
        )
        self._blit_clamped_line(
            self._small_font,
            subtitle_text,
            (60, 78),
            (212, 213, 222),
            header_rect.width - 260,
        )
        self._blit_clamped_line(
            self._small_font,
            f"鎿嶄綔鍛?{operator_name}",
            (badge_rect.x + 18, badge_rect.y + 9),
            (36, 28, 18),
            badge_rect.width - 36,
        )

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

        self._blit_clamped_line(
            self._title_font,
            title,
            (rect.x + 18, rect.y + 16),
            (244, 240, 233),
            rect.width - 36,
            selected=focused,
        )
        self._blit_clamped_line(
            self._small_font,
            subtitle,
            (rect.x + 18, rect.y + 54),
            accent,
            rect.width - 36,
            selected=focused,
        )

        y = rect.y + 92
        for block in body_blocks:
            block_rect = self._blit_preview_block(
                self._small_font,
                block,
                (rect.x + 18, y),
                (221, 225, 231),
                rect.width - 36,
                4,
                line_gap=4,
                selected=focused,
            )
            y += block_rect.height + 12
            if y > rect.bottom - 40:
                break

        self._blit_clamped_line(
            self._small_font,
            "Enter 鏌ョ湅瀹屾暣鍐呭",
            (rect.x + 18, rect.bottom - 28),
            accent,
            rect.width - 36,
            selected=focused,
        )

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

            self._blit_clamped_line(
                self._small_font,
                role.display_name,
                (card.x + 12, card.y + 6),
                title_color,
                220,
                selected=selected,
            )
            self._blit_clamped_line(
                self._small_font,
                role.primary_tool_name,
                (card.right - 12, card.y + 6),
                body_color,
                250,
                align="right",
                selected=selected,
            )

    def _draw_detail_modal(self, modal: Any) -> None:
        overlay = pygame.Surface((self._width, self._height), pygame.SRCALPHA)
        overlay.fill((8, 10, 14, 176))
        self._surface.blit(overlay, (0, 0))

        rect = pygame.Rect(148, 86, self._width - 296, self._height - 172)
        pygame.draw.rect(self._surface, (16, 18, 24), rect, border_radius=22)
        pygame.draw.rect(self._surface, (219, 188, 132), rect, width=2, border_radius=22)

        self._blit_clamped_line(
            self._title_font,
            modal.title,
            (rect.x + 24, rect.y + 20),
            (247, 233, 204),
            rect.width - 48,
        )
        self._blit_clamped_line(
            self._small_font,
            modal.subtitle,
            (rect.x + 24, rect.y + 58),
            (220, 223, 232),
            rect.width - 48,
        )

        body_text = "\n\n".join(block or " " for block in modal.body_lines)
        body_top = rect.y + 98
        footer_top = rect.bottom - 34
        line_height = self._small_font.get_height() + 6
        max_lines = max(1, (footer_top - body_top) // max(line_height, 1))
        self._blit_preview_block(
            self._small_font,
            body_text,
            (rect.x + 24, body_top),
            (232, 235, 241),
            rect.width - 48,
            max_lines,
            line_gap=6,
        )
        self._blit_clamped_line(
            self._small_font,
            modal.footer,
            (rect.x + 24, rect.bottom - 32),
            (238, 199, 132),
            rect.width - 48,
        )

    def _draw_input_modal(
        self,
        title: str,
        value: str,
        masked: bool,
        *,
        hint_text: str = "",
        composition: str = "",
        cursor_index: int = 0,
        multiline: bool = False,
    ) -> None:
        overlay = pygame.Surface((self._width, self._height), pygame.SRCALPHA)
        overlay.fill((6, 8, 12, 176))
        self._surface.blit(overlay, (0, 0))

        rect_height = 248 if multiline else 196
        rect = pygame.Rect(236, 208 if multiline else 220, self._width - 472, rect_height)
        pygame.draw.rect(self._surface, (16, 18, 24), rect, border_radius=22)
        pygame.draw.rect(self._surface, (219, 188, 132), rect, width=2, border_radius=22)
        self._blit_clamped_line(
            self._title_font,
            title,
            (rect.x + 24, rect.y + 20),
            (247, 233, 204),
            rect.width - 48,
        )
        self._blit_clamped_line(
            self._small_font,
            "回车确认输入 | Ctrl+V 粘贴 | Esc 取消"
            if not multiline
            else "回车换行 | Ctrl+V 粘贴 | Ctrl+Enter 确认 | Esc 取消",
            (rect.x + 24, rect.y + 56),
            (220, 223, 232),
            rect.width - 48,
        )

        if composition:
            composition_rect = pygame.Rect(rect.x + 22, rect.y + 72, rect.width - 44, 20)
            pygame.draw.rect(self._surface, (69, 52, 30), composition_rect, border_radius=8)
            pygame.draw.rect(self._surface, (235, 202, 140), composition_rect, width=1, border_radius=8)
            self._blit_clamped_line(
                self._small_font,
                f"输入法候选: {composition}",
                (composition_rect.x + 10, composition_rect.y + 2),
                (247, 233, 204),
                composition_rect.width - 20,
            )

        input_rect = pygame.Rect(
            rect.x + 22,
            rect.y + 92,
            rect.width - 44,
            92 if multiline else 52,
        )
        pygame.draw.rect(self._surface, (37, 42, 52), input_rect, border_radius=12)
        pygame.draw.rect(self._surface, (226, 193, 128), input_rect, width=2, border_radius=12)
        display_value = value if not masked else "*" * len(value)
        bounded_cursor = min(max(cursor_index, 0), len(display_value))
        preview_value = f"{display_value[:bounded_cursor]}|{display_value[bounded_cursor:]}"

        if multiline:
            lines = wrap_text(preview_value or " ", self._small_font, input_rect.width - 24)
            y = input_rect.y + 12
            max_height = input_rect.bottom - 10
            for line in lines[:4]:
                rendered = self._small_font.render(line, True, (244, 240, 233))
                self._surface.blit(rendered, (input_rect.x + 12, y))
                y += rendered.get_height() + 6
                if y > max_height:
                    break
            self._register_tooltip(input_rect, display_value or " ", selected=True, preferred_width=520)
        else:
            self._blit_clamped_line(
                self._small_font,
                preview_value or "|",
                (input_rect.x + 12, input_rect.y + 15),
                (244, 240, 233),
                input_rect.width - 24,
                selected=True,
                tooltip_text=display_value or " ",
            )

        footer_y = input_rect.bottom + 10
        if hint_text:
            self._blit_preview_block(
                self._small_font,
                hint_text,
                (rect.x + 24, footer_y),
                (212, 217, 226),
                rect.width - 48,
                2,
                line_gap=4,
            )

    def _panel(self, rect: pygame.Rect, fill: Color) -> None:
        pygame.draw.rect(self._surface, fill, rect, border_radius=18)
        pygame.draw.rect(self._surface, (123, 118, 103), rect, width=2, border_radius=18)

    def _section_title(self, text: str, x: int, y: int) -> None:
        self._blit_clamped_line(
            self._title_font,
            text,
            (x, y),
            (243, 234, 219),
            max(120, self._width - x - 40),
        )

    def _section_subtitle(self, text: str, x: int, y: int) -> None:
        self._blit_clamped_line(
            self._small_font,
            text,
            (x, y),
            (235, 192, 125),
            max(120, self._width - x - 40),
        )

    def _draw_footer(self, text: str, status_text: str | None) -> None:
        footer_rect = pygame.Rect(34, self._height - 48, self._width - 68, 30)
        main_width = footer_rect.width - 320 if status_text else footer_rect.width - 8
        self._blit_clamped_line(
            self._small_font,
            text,
            (footer_rect.x + 4, footer_rect.y + 4),
            (224, 229, 235),
            max(80, main_width),
        )
        if status_text:
            self._blit_clamped_line(
                self._small_font,
                status_text,
                (footer_rect.right - 4, footer_rect.y + 4),
                (237, 203, 138),
                300,
                align="right",
            )

    def _field_label(self, field_name: str, fields: list[Any]) -> str:
        for field in fields:
            if isinstance(field, tuple) and len(field) >= 2:
                candidate_name, label = field[0], field[1]
            else:
                candidate_name = getattr(field, "key", None)
                label = getattr(field, "label", field_name)
            if candidate_name == field_name:
                return str(label)
        return field_name

    def _format_setting_value(self, field_name: str, field_kind: str, draft: Any) -> str:
        value = getattr(draft, field_name)
        if field_kind == "bool":
            return "是" if value else "否"
        if field_name == "avatar_gender":
            return "男" if str(value).strip().lower() == "male" else "女"
        if field_name == "api_key":
            return self._mask_secret(str(value))
        return str(value) or "(空)"

    def _main_menu_hint(self, option: str) -> str:
        hints = {
            "开始游戏": "进入角色创建并开始新案件。",
            "自定义剧本": "进入自定义剧本编辑器。",
            "选项设置": "调整显示和 AI 请求配置。",
            "退出游戏": "关闭游戏。",
        }
        return hints.get(option, "")

    def _mask_secret(self, value: str) -> str:
        if not value:
            return "(未设置)"
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"
