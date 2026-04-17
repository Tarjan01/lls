from __future__ import annotations

from types import SimpleNamespace

import pygame
import pytest

from reverse_detective.renderer import MenuRenderer, TooltipTarget
from reverse_detective.utils.text import fit_text, preview_wrapped_text


def test_fit_text_adds_ellipsis_when_line_is_too_wide() -> None:
    pygame.init()
    try:
        font = pygame.font.SysFont("microsoftyaheiui", 20)
        max_width = font.size("这是一个")[0]
        preview, truncated = fit_text("这是一个明显过长的标题文本", font, max_width)

        assert truncated is True
        assert preview.endswith("…")
        assert font.size(preview)[0] <= max_width
    finally:
        pygame.quit()


def test_preview_wrapped_text_reports_block_truncation() -> None:
    pygame.init()
    try:
        font = pygame.font.SysFont("microsoftyaheiui", 18)
        lines, truncated = preview_wrapped_text(
            "第一段内容很长，需要被换行处理。第二段内容同样很长，需要继续占用更多空间。",
            font,
            max_width=font.size("第一段内容很长")[0],
            max_lines=2,
        )

        assert truncated is True
        assert len(lines) == 2
        assert lines[-1].endswith("…")
    finally:
        pygame.quit()


def test_menu_renderer_registers_hover_tooltip_for_truncated_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((1280, 720))
    screen = pygame.display.get_surface()
    assert screen is not None

    long_option = "开始游戏并进入一个名字特别特别长的测试菜单项，用来验证悬停时显示完整文本"
    background = SimpleNamespace(
        game_title="反向侦探案件模拟台终端界面标题非常长非常长",
        game_subtitle="这是一个用于验证标题区域会自动省略并保留完整提示文本的副标题",
        operator_name="代号非常长的操作员名称",
        menu_intro="这是一段很长的菜单简介，用来验证主菜单左侧说明区域在超过可显示行数时会使用省略号并注册完整文本 tooltip。"
        * 2,
        background="这是一段很长的背景简介，用来验证主菜单背景信息在卡片里被截断后仍然可以通过悬停查看完整文本。"
        * 3,
    )

    renderer = MenuRenderer(screen, 1280, 720)
    try:
        renderer.draw_main_menu(background, [long_option, "退出游戏"], 0, "状态提示文本也非常长，需要截断")

        assert any(target.text == long_option for target in renderer._tooltip_targets)
        assert len(renderer._tooltip_targets) >= 2
    finally:
        pygame.quit()


def test_tooltip_overlay_only_renders_when_hovered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    pygame.display.set_mode((640, 360))
    screen = pygame.display.get_surface()
    assert screen is not None

    renderer = MenuRenderer(screen, 640, 360)
    target = TooltipTarget(
        rect=pygame.Rect(120, 120, 120, 24),
        text="这是一段只应在鼠标悬停时显示的完整提示文本。",
        selected=True,
        preferred_width=260,
    )

    try:
        screen.fill((8, 12, 18))
        renderer._tooltip_targets = [target]
        renderer._mouse_pos = (12, 12)
        before_idle = pygame.image.tobytes(screen, "RGBA")
        renderer._draw_tooltip_overlay()
        after_idle = pygame.image.tobytes(screen, "RGBA")

        screen.fill((8, 12, 18))
        renderer._tooltip_targets = [target]
        renderer._mouse_pos = (126, 126)
        before_hover = pygame.image.tobytes(screen, "RGBA")
        renderer._draw_tooltip_overlay()
        after_hover = pygame.image.tobytes(screen, "RGBA")

        assert after_idle == before_idle
        assert after_hover != before_hover
    finally:
        pygame.quit()
