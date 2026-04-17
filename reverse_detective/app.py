"""Application entrypoint for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from queue import Empty, Queue
import threading
from typing import Literal

import pygame

from reverse_detective.ai_client import AIClientError, ReverseDetectiveAIClient
from reverse_detective.audio import AudioController
from reverse_detective.config import (
    AIConfig,
    AppConfig,
    DisplayConfig,
    PlayerConfig,
    load_api_key,
    load_config,
    save_api_key,
    save_config,
)
from reverse_detective.custom_story import (
    CustomStoryDraft,
    CustomStoryEditorField,
    DEFAULT_CUSTOM_DETECTIVE_IDENTITY,
    DEFAULT_CUSTOM_STORY_SUBTITLE,
    apply_custom_story_action,
    build_custom_story_editor_fields,
    is_custom_story_editor_key,
    remove_custom_story_field,
    update_custom_story_field,
    validate_custom_story_draft,
    write_custom_story,
)
from reverse_detective.game_state import GameSessionState
from reverse_detective.models import (
    GameBackgroundDefinition,
    Interactable,
    SceneState,
    StoryDefinition,
    StoryPremise,
    StoryRole,
)
from reverse_detective.renderer import MenuRenderer, Renderer
from reverse_detective.story_loader import (
    BACKGROUND_FILE_NAME,
    DEFAULT_STORIES_DIR,
    build_story_premise,
    load_game_background,
    load_story_catalog,
)
from reverse_detective.utils.text_input import TextInputSession


PLAY_AREA_HEIGHT = 520
PLAYER_SIZE = (42, 62)
PLAYER_SPEED = 240.0
MAIN_MENU_OPTIONS = ("开始游戏", "自定义剧本", "选项设置", "退出游戏")
PLAYER_AVATAR_OPTIONS = ("male", "female")
SETTINGS_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("window_title", "窗口标题", "text"),
    ("detective_name", "侦探名字", "text"),
    ("avatar_gender", "主控形象", "choice"),
    ("fps", "帧率 FPS", "int"),
    ("base_url", "请求 Base URL", "text"),
    ("api_key", "API Key", "secret"),
    ("model", "模型名称", "text"),
    ("reasoning_effort", "推理强度", "text"),
    ("timeout_seconds", "超时秒数", "float"),
    ("disable_response_storage", "禁用响应存储", "bool"),
    ("use_mock_when_unconfigured", "未配置时使用本地 Mock", "bool"),
    ("fallback_to_mock_on_error", "请求失败时回退 Mock", "bool"),
)

MenuMode = Literal["main_menu", "story_browser", "settings", "custom_story", "game"]
BrowserFocus = Literal["story", "role"]


@dataclass(frozen=True, slots=True)
class WorkerResult:
    request_id: int
    kind: str
    scene: SceneState | None
    error: str | None


@dataclass(frozen=True, slots=True)
class MenuSelection:
    story_index: int
    role_index: int


@dataclass(frozen=True, slots=True)
class DetailModal:
    title: str
    subtitle: str
    body_lines: tuple[str, ...]
    footer: str


@dataclass(slots=True)
class SettingsDraft:
    window_title: str
    detective_name: str
    avatar_gender: str
    fps: int
    base_url: str
    api_key: str
    model: str
    reasoning_effort: str
    timeout_seconds: float
    disable_response_storage: bool
    use_mock_when_unconfigured: bool
    fallback_to_mock_on_error: bool

    @classmethod
    def from_config(cls, config: AppConfig, api_key: str) -> "SettingsDraft":
        return cls(
            window_title=config.display.title,
            detective_name=config.player.detective_name,
            avatar_gender=config.player.avatar_gender,
            fps=config.display.fps,
            base_url=config.ai.base_url,
            api_key=api_key,
            model=config.ai.model,
            reasoning_effort=config.ai.reasoning_effort,
            timeout_seconds=config.ai.timeout_seconds,
            disable_response_storage=config.ai.disable_response_storage,
            use_mock_when_unconfigured=config.ai.use_mock_when_unconfigured,
            fallback_to_mock_on_error=config.ai.fallback_to_mock_on_error,
        )

    def to_config(self, current_config: AppConfig) -> AppConfig:
        avatar_gender = self.avatar_gender.strip().lower()
        if avatar_gender not in PLAYER_AVATAR_OPTIONS:
            avatar_gender = current_config.player.avatar_gender
        return AppConfig(
            display=DisplayConfig(
                title=self.window_title.strip(),
                width=current_config.display.width,
                height=current_config.display.height,
                fps=self.fps,
            ),
            ai=AIConfig(
                provider=current_config.ai.provider,
                base_url=self.base_url.strip(),
                model=self.model.strip(),
                reasoning_effort=self.reasoning_effort.strip() or "high",
                timeout_seconds=self.timeout_seconds,
                disable_response_storage=self.disable_response_storage,
                use_mock_when_unconfigured=self.use_mock_when_unconfigured,
                fallback_to_mock_on_error=self.fallback_to_mock_on_error,
                credentials_path=current_config.ai.credentials_path,
            ),
            player=PlayerConfig(
                detective_name=self.detective_name.strip() or current_config.player.detective_name,
                avatar_gender=avatar_gender,
            ),
        )


class GameApp:
    """Main game application with menu flow, settings and background scene generation."""

    def __init__(self, config: AppConfig, *, stories_dir: Path | None = None):
        self._config = config
        self._stories_dir = (stories_dir or DEFAULT_STORIES_DIR).resolve()
        self._background: GameBackgroundDefinition = load_game_background(
            self._stories_dir / BACKGROUND_FILE_NAME
        )
        self._stories = load_story_catalog(self._stories_dir)
        self._menu_selection = MenuSelection(story_index=0, role_index=0)
        self._main_menu_index = 0
        self._story_focus: BrowserFocus = "story"
        self._detail_modal: DetailModal | None = None
        self._mode: MenuMode = "main_menu"
        self._premise: StoryPremise | None = None
        self._session: GameSessionState | None = None
        self._result_queue: Queue[WorkerResult] = Queue()
        self._elapsed_seconds = 0.0
        self._running = True
        self._request_serial = 0
        self._settings_index = 0
        self._custom_story_index = 0
        self._input_editor: TextInputSession | None = None
        self._status_text: str | None = None
        self._settings_draft = SettingsDraft.from_config(
            config,
            load_api_key(config.ai.credentials_path, config.ai.provider),
        )
        self._custom_story_draft = CustomStoryDraft.blank()

        pygame.init()
        pygame.display.set_caption(config.display.title)
        self._screen = pygame.display.set_mode((config.display.width, config.display.height))
        try:
            pygame.scrap.init()
        except pygame.error:
            pass
        self._clock = pygame.time.Clock()
        self._game_renderer = Renderer(
            self._screen,
            config.display.width,
            config.display.height,
            PLAY_AREA_HEIGHT,
        )
        self._menu_renderer = MenuRenderer(
            self._screen,
            config.display.width,
            config.display.height,
        )
        self._audio = AudioController()
        self._ai_client = self._build_ai_client(config.ai)
        self._schedule_initial_scene_prefetch()

    def run(self) -> None:
        try:
            while self._running:
                delta_time = self._clock.tick(self._config.display.fps) / 1000
                self._elapsed_seconds += delta_time

                self._handle_events()
                self._update_movement(delta_time)
                self._poll_worker_results()
                self._update_active_interactable()
                self._draw()
        finally:
            self._audio.close()
            self._ai_client.close()
            pygame.quit()

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_keydown(event.key, getattr(event, "unicode", ""))
            elif event.type == pygame.TEXTINPUT:
                self._handle_textinput(getattr(event, "text", ""))
            elif event.type == pygame.TEXTEDITING:
                self._handle_textediting(getattr(event, "text", ""))
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._handle_mousebuttondown(event.button, event.pos)
            elif event.type == pygame.MOUSEWHEEL:
                self._handle_mousewheel(event.y)

    def _handle_keydown(self, key: int, text: str = "") -> None:
        if self._input_editor is not None:
            self._handle_input_keydown(key, text)
            return

        if self._detail_modal is not None:
            if key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE, pygame.K_BACKSPACE):
                self._detail_modal = None
            return

        if self._handle_selected_text_keydown(key):
            return

        if self._mode == "main_menu":
            if key == pygame.K_ESCAPE:
                self._running = False
                return
            self._handle_main_menu_keydown(key)
            return

        if key == pygame.K_ESCAPE:
            self._return_to_main_menu("已返回主菜单")
            return

        if self._mode == "story_browser":
            self._handle_story_browser_keydown(key)
            return

        if self._mode == "settings":
            self._handle_settings_keydown(key)
            return

        if self._mode == "custom_story":
            self._handle_custom_story_keydown(key)
            return

        self._handle_game_keydown(key)

    def _handle_mousebuttondown(self, button: int, position: tuple[int, int]) -> None:
        if self._input_editor is not None or self._detail_modal is not None:
            return

        if button == 1:
            if self._mode == "game":
                action = self._game_renderer.consume_action_click(position)
                if action == "open_freeform_action":
                    self._begin_freeform_action_input()
                    return
            renderer = self._active_text_renderer()
            if renderer is not None and renderer.handle_text_selection_click(position):
                return

        if button == 4:
            self._handle_mousewheel(1)
        elif button == 5:
            self._handle_mousewheel(-1)

    def _handle_mousewheel(self, delta: int) -> None:
        renderer = self._active_text_renderer()
        if renderer is None:
            return
        renderer.scroll_selected_text(-delta * 3)

    def _handle_selected_text_keydown(self, key: int) -> bool:
        renderer = self._active_text_renderer()
        if renderer is None or not renderer.has_selected_text():
            return False

        if key == pygame.K_ESCAPE:
            renderer.clear_selected_text()
            return True
        if key == pygame.K_UP:
            return renderer.scroll_selected_text(-1)
        if key == pygame.K_DOWN:
            return renderer.scroll_selected_text(1)
        if key == pygame.K_PAGEUP:
            return renderer.scroll_selected_text(-6)
        if key == pygame.K_PAGEDOWN:
            return renderer.scroll_selected_text(6)
        return False

    def _handle_main_menu_keydown(self, key: int) -> None:
        if key == pygame.K_UP:
            self._main_menu_index = (self._main_menu_index - 1) % len(MAIN_MENU_OPTIONS)
            return

        if key == pygame.K_DOWN:
            self._main_menu_index = (self._main_menu_index + 1) % len(MAIN_MENU_OPTIONS)
            return

        if key not in (pygame.K_RETURN, pygame.K_SPACE):
            return

        self._audio.play_confirm(MAIN_MENU_OPTIONS[self._main_menu_index])
        if self._main_menu_index == 0:
            self._enter_story_browser()
        elif self._main_menu_index == 1:
            self._enter_custom_story()
        elif self._main_menu_index == 2:
            self._enter_settings()
        else:
            self._running = False

    def _handle_story_browser_keydown(self, key: int) -> None:
        if key == pygame.K_LEFT:
            self._select_story(self._menu_selection.story_index - 1)
            return

        if key == pygame.K_RIGHT:
            self._select_story(self._menu_selection.story_index + 1)
            return

        if key == pygame.K_UP:
            self._select_role(self._menu_selection.role_index - 1)
            return

        if key == pygame.K_DOWN:
            self._select_role(self._menu_selection.role_index + 1)
            return

        if key == pygame.K_TAB:
            self._story_focus = "role" if self._story_focus == "story" else "story"
            return

        if key == pygame.K_BACKSPACE:
            self._return_to_main_menu()
            return

        if key == pygame.K_RETURN:
            self._audio.play_confirm("story_detail")
            self._open_detail_modal()
            return

        if key == pygame.K_SPACE:
            self._audio.play_confirm("start_story", self.current_story.title)
            self._start_selected_story()

    def _handle_settings_keydown(self, key: int) -> None:
        field_name, _, field_kind = SETTINGS_FIELDS[self._settings_index]

        if key == pygame.K_UP:
            self._settings_index = (self._settings_index - 1) % len(SETTINGS_FIELDS)
            return

        if key == pygame.K_DOWN:
            self._settings_index = (self._settings_index + 1) % len(SETTINGS_FIELDS)
            return

        if key == pygame.K_BACKSPACE:
            self._return_to_main_menu()
            return

        if key in (pygame.K_LEFT, pygame.K_RIGHT):
            if field_kind == "bool":
                self._toggle_setting(field_name)
                self._audio.play_confirm(field_name)
                return
            if field_kind == "choice":
                direction = -1 if key == pygame.K_LEFT else 1
                self._cycle_choice_setting(field_name, direction)
                self._audio.play_confirm(field_name, str(getattr(self._settings_draft, field_name)))
                return
            return

        if key == pygame.K_RETURN:
            if field_kind == "bool":
                self._toggle_setting(field_name)
                self._audio.play_confirm(field_name)
            elif field_kind == "choice":
                self._cycle_choice_setting(field_name, 1)
                self._audio.play_confirm(field_name, str(getattr(self._settings_draft, field_name)))
            else:
                self._begin_input_edit(
                    field_name=field_name,
                    title=self._field_label(field_name),
                    value=str(getattr(self._settings_draft, field_name)),
                    secret=field_kind == "secret",
                    hint_text=self._input_hint(field_name, field_kind),
                )
            return

        if key == pygame.K_s:
            self._save_settings()
            return

        if key == pygame.K_d:
            self._reset_settings_draft("已放弃未保存的修改")

    def _handle_custom_story_keydown(self, key: int) -> None:
        fields = self._custom_story_fields()
        if not fields:
            return

        field = fields[self._custom_story_index]

        if key == pygame.K_UP:
            self._custom_story_index = (self._custom_story_index - 1) % len(fields)
            return

        if key == pygame.K_DOWN:
            self._custom_story_index = (self._custom_story_index + 1) % len(fields)
            return

        if key == pygame.K_BACKSPACE:
            self._return_to_main_menu()
            return

        if key == pygame.K_s:
            self._save_custom_story()
            return

        if key == pygame.K_d:
            self._reset_custom_story_draft("已放弃未保存的自定义卷宗。")
            return

        if key == pygame.K_DELETE:
            try:
                self._status_text = remove_custom_story_field(self._custom_story_draft, field.key)
                remaining_fields = self._custom_story_fields()
                self._custom_story_index = 0 if not remaining_fields else min(
                    self._custom_story_index,
                    len(remaining_fields) - 1,
                )
            except ValueError as exc:
                self._status_text = str(exc)
            return

        if key != pygame.K_RETURN:
            return

        if field.kind == "action":
            try:
                self._status_text = apply_custom_story_action(self._custom_story_draft, field.key)
                self._custom_story_index = min(
                    self._custom_story_index,
                    max(len(self._custom_story_fields()) - 1, 0),
                )
            except ValueError as exc:
                self._status_text = str(exc)
            return

        if field.kind == "readonly":
            return

        self._begin_input_edit(
            field_name=field.key,
            title=field.label,
            value=field.value,
            multiline=field.kind == "multiline",
            max_length=1600 if field.kind == "multiline" else 160,
            hint_text=field.hint_text,
        )

    def _handle_input_keydown(self, key: int, text: str) -> None:
        editor = self._input_editor
        if editor is None:
            return

        if key == pygame.K_ESCAPE:
            self._cancel_input_edit()
            self._status_text = "已取消输入。"
            return

        if key == pygame.K_v and (pygame.key.get_mods() & pygame.KMOD_CTRL):
            self._paste_clipboard_text()
            return

        if key == pygame.K_LEFT:
            editor.move_left()
            editor.clear_composition()
            return

        if key == pygame.K_RIGHT:
            editor.move_right()
            editor.clear_composition()
            return

        if key == pygame.K_HOME:
            editor.move_home()
            editor.clear_composition()
            return

        if key == pygame.K_END:
            editor.move_end()
            editor.clear_composition()
            return

        if key == pygame.K_DELETE:
            editor.delete_forward()
            editor.clear_composition()
            return

        if key == pygame.K_TAB:
            return

        if key == pygame.K_RETURN and editor.multiline:
            if pygame.key.get_mods() & pygame.KMOD_CTRL:
                self._commit_input_edit()
            else:
                editor.insert_text("\n")
                editor.clear_composition()
            return

        if key == pygame.K_RETURN:
            self._commit_input_edit()
            return

        if key == pygame.K_BACKSPACE:
            editor.backspace()
            editor.clear_composition()
            return

        if text and text.isprintable() and not self._should_rely_on_textinput():
            editor.insert_text(text)
            editor.clear_composition()

    def _handle_textinput(self, text: str) -> None:
        editor = self._input_editor
        if editor is None or not text:
            return
        editor.insert_text(text)
        editor.clear_composition()

    def _handle_textediting(self, text: str) -> None:
        editor = self._input_editor
        if editor is None:
            return
        editor.set_composition(text)

    def _begin_input_edit(
        self,
        *,
        field_name: str,
        title: str,
        value: str,
        multiline: bool = False,
        secret: bool = False,
        max_length: int = 240,
        hint_text: str = "",
        placeholder: str = "",
    ) -> None:
        self._input_editor = TextInputSession(
            field_name=field_name,
            title=title,
            value=value,
            multiline=multiline,
            secret=secret,
            max_length=max_length,
            hint_text=hint_text,
            placeholder=placeholder,
            cursor=len(value),
        )
        self._activate_text_input(multiline=multiline)

    def _cancel_input_edit(self) -> None:
        self._input_editor = None
        self._deactivate_text_input()

    def _activate_text_input(self, *, multiline: bool) -> None:
        try:
            pygame.key.start_text_input()
            pygame.key.set_text_input_rect(self._input_target_rect(multiline))
        except pygame.error:
            return

    def _refresh_text_input_rect(self) -> None:
        editor = self._input_editor
        if editor is None:
            return
        try:
            pygame.key.set_text_input_rect(self._input_target_rect(editor.multiline))
        except pygame.error:
            return

    def _deactivate_text_input(self) -> None:
        try:
            pygame.key.stop_text_input()
        except pygame.error:
            return

    def _input_target_rect(self, multiline: bool) -> pygame.Rect:
        modal_width = self._config.display.width - 472
        modal_height = 248 if multiline else 196
        modal_x = 236
        modal_y = 208 if multiline else 220
        return pygame.Rect(
            modal_x + 22,
            modal_y + 92,
            modal_width - 44,
            92 if multiline else 52,
        )

    def _paste_clipboard_text(self) -> None:
        editor = self._input_editor
        if editor is None:
            return
        try:
            raw_clipboard = pygame.scrap.get(pygame.SCRAP_TEXT)
        except (pygame.error, AttributeError):
            raw_clipboard = None
        if raw_clipboard is None:
            return
        if isinstance(raw_clipboard, bytes):
            clipboard_text = raw_clipboard.decode("utf-8", errors="ignore").replace("\x00", "")
        else:
            clipboard_text = str(raw_clipboard)
        if editor.multiline:
            clipboard_text = clipboard_text.replace("\r\n", "\n").replace("\r", "\n")
        else:
            clipboard_text = clipboard_text.replace("\r", " ").replace("\n", " ")
        editor.insert_text(clipboard_text)
        editor.clear_composition()

    def _should_rely_on_textinput(self) -> bool:
        return hasattr(pygame, "TEXTINPUT")

    def _begin_freeform_action_input(self) -> None:
        if (
            self._mode != "game"
            or self._session is None
            or self._session.loading
            or self._session.current_scene.is_terminal
        ):
            return
        self._begin_input_edit(
            field_name="__freeform_action__",
            title="自由行动",
            value="",
            multiline=True,
            max_length=420,
            hint_text=(
                "写下不在当前选项里的行动。确认后会立即发送给 AI 裁定。"
                "建议写清对象、动作和目标，例如：伪装成馆员去套话，或把钥匙藏进清洁车。"
            ),
            placeholder="输入你的自由行动",
        )

    def _submit_freeform_action(self, raw_value: str) -> None:
        if self._session is None:
            return
        cleaned = raw_value.strip()
        if not cleaned:
            self._status_text = "自由行动不能为空。"
            return
        if self._session.loading or self._session.current_scene.is_terminal:
            return
        choice = self._session.build_freeform_choice(cleaned)
        self._audio.play_effect(choice.sfx, choice.label, choice.action_id)
        resolution = self._session.apply_choice(choice)
        if resolution.requires_immediate_ai:
            self._submit_settlement_request(request_type="freeform_action")

    def _handle_game_keydown(self, key: int) -> None:
        if key == pygame.K_m:
            self._return_to_main_menu("已返回主菜单")
            return

        if key == pygame.K_r:
            self._submit_initial_request()
            return

        if self._mode != "game" or self._session is None:
            return

        if key == pygame.K_c:
            self._begin_freeform_action_input()
            return

        if key == pygame.K_t and self._session.can_force_settle:
            self._submit_settlement_request()
            return

        if self._session.loading:
            if key in (pygame.K_LEFT, pygame.K_PAGEUP):
                self._session.browse_text_history(-1)
                return
            if key in (pygame.K_RIGHT, pygame.K_PAGEDOWN):
                self._session.browse_text_history(1)
                return

        if self._session.loading or self._session.current_scene.is_terminal or self._session.needs_settlement:
            return

        if key == pygame.K_UP:
            self._session.cycle_options(-1)
            return

        if key == pygame.K_DOWN:
            self._session.cycle_options(1)
            return

        if key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_e):
            choice = self._session.choose_option_by_index(self._session.selected_option_index)
            if choice is not None:
                self._audio.play_effect(choice.sfx, choice.label, choice.action_id)
                resolution = self._session.apply_choice(choice)
                if resolution.requires_immediate_ai:
                    self._submit_settlement_request(request_type="forced_immediate_choice")
                elif resolution.should_settle:
                    self._submit_settlement_request()
            return

        if pygame.K_1 <= key <= pygame.K_9:
            option_index = key - pygame.K_1
            choice = self._session.choose_option_by_index(option_index)
            if choice is not None:
                self._audio.play_effect(choice.sfx, choice.label, choice.action_id)
                resolution = self._session.apply_choice(choice)
                if resolution.requires_immediate_ai:
                    self._submit_settlement_request(request_type="forced_immediate_choice")
                elif resolution.should_settle:
                    self._submit_settlement_request()

    def _update_movement(self, delta_time: float) -> None:
        if self._mode != "game" or self._session is None:
            return

        if self._session.loading or self._session.current_scene.is_terminal:
            return

        pressed = pygame.key.get_pressed()
        horizontal = float(pressed[pygame.K_d]) - float(pressed[pygame.K_a])
        vertical = float(pressed[pygame.K_s]) - float(pressed[pygame.K_w])

        if horizontal == 0 and vertical == 0:
            return

        length = max((horizontal**2 + vertical**2) ** 0.5, 1.0)
        x, y = self._session.player_position
        x += horizontal / length * PLAYER_SPEED * delta_time
        y += vertical / length * PLAYER_SPEED * delta_time

        half_width = PLAYER_SIZE[0] / 2
        half_height = PLAYER_SIZE[1] / 2
        clamped_x = min(max(x, half_width + 24), self._config.display.width - half_width - 24)
        clamped_y = min(max(y, half_height + 80), PLAY_AREA_HEIGHT - half_height - 24)
        self._session.set_player_position(clamped_x, clamped_y)

    def _poll_worker_results(self) -> None:
        while True:
            try:
                result = self._result_queue.get_nowait()
            except Empty:
                return

            if self._mode != "game" or self._session is None:
                continue

            if result.request_id != self._request_serial:
                continue

            if result.error:
                self._session.fail_action(result.error)
                continue

            if result.scene is None:
                self._session.fail_action("AI 没有返回有效场景。")
                continue

            if result.kind == "initial":
                self._session.finish_initial_scene(result.scene)
                self._audio.play_success("initial_scene_ready", result.scene.scene.bgm)
            else:
                self._session.finish_settlement(result.scene)
                self._audio.play_success("round_settled", result.scene.scene.bgm)

    def _update_active_interactable(self) -> None:
        if self._mode != "game" or self._session is None:
            return

        if (
            self._session.loading
            or self._session.current_scene.is_terminal
            or self._session.needs_settlement
        ):
            self._session.set_active_interactable(None)
            return

        player_rect = self._player_rect()
        best_match: tuple[float, str] | None = None

        for interactable in self._session.current_scene.interactables:
            if not self._session.available_options_for(interactable):
                continue

            trigger_rect = self._trigger_rect(interactable)
            if not player_rect.colliderect(trigger_rect):
                continue

            distance = (interactable.position[0] - player_rect.centerx) ** 2 + (
                interactable.position[1] - player_rect.centery
            ) ** 2
            if best_match is None or distance < best_match[0]:
                best_match = (distance, interactable.id)

        self._session.set_active_interactable(None if best_match is None else best_match[1])

    def _player_rect(self) -> pygame.Rect:
        if self._session is None:
            return pygame.Rect(0, 0, PLAYER_SIZE[0], PLAYER_SIZE[1])
        x, y = self._session.player_position
        return pygame.Rect(
            int(x - PLAYER_SIZE[0] / 2),
            int(y - PLAYER_SIZE[1] / 2),
            PLAYER_SIZE[0],
            PLAYER_SIZE[1],
        )

    def _trigger_rect(self, interactable: Interactable) -> pygame.Rect:
        return pygame.Rect(interactable.position[0] - 72, interactable.position[1] - 72, 144, 144)

    def _submit_initial_request(self) -> None:
        if self._session is None or self._premise is None:
            return

        self._request_serial += 1
        request_id = self._request_serial
        self._session.reset_for_restart()
        self._session.begin_initial_load()
        premise_snapshot = self._premise
        worker = threading.Thread(
            target=self._run_initial_request,
            args=(request_id, premise_snapshot),
            daemon=True,
        )
        worker.start()

    def _submit_settlement_request(
        self,
        *,
        request_type: Literal[
            "round_settlement",
            "forced_immediate_choice",
            "freeform_action",
        ] = "round_settlement",
    ) -> None:
        if (
            self._session is None
            or self._premise is None
            or self._session.loading
            or not self._session.round_actions
        ):
            return

        self._request_serial += 1
        request_id = self._request_serial
        settled_history_snapshot = list(self._session.settled_action_history)
        round_actions_snapshot = list(self._session.round_actions)
        scene_snapshot = self._session.current_scene
        premise_snapshot = self._premise
        if request_type == "forced_immediate_choice":
            loading_hint = "关键行动已触发，AI 正在立即裁决本轮走向。"
            self._session.local_message = loading_hint
            latest_turn = round_actions_snapshot[-1].turn_index if round_actions_snapshot else None
            self._session.record_system_text("即时裁决", loading_hint, turn_index=latest_turn)
        elif request_type == "freeform_action":
            loading_hint = "自由行动已提交，AI 正在根据你的描述即时裁定。"
            self._session.local_message = loading_hint
            latest_turn = round_actions_snapshot[-1].turn_index if round_actions_snapshot else None
            self._session.record_system_text("自由行动裁决", loading_hint, turn_index=latest_turn)
        self._session.begin_settlement()
        worker = threading.Thread(
            target=self._run_settlement_request,
            args=(
                request_id,
                premise_snapshot,
                settled_history_snapshot,
                round_actions_snapshot,
                scene_snapshot,
                request_type,
            ),
            daemon=True,
        )
        worker.start()

    def _run_initial_request(self, request_id: int, premise: StoryPremise) -> None:
        try:
            scene = self._ai_client.generate_initial_scene(premise)
            self._result_queue.put(
                WorkerResult(request_id=request_id, kind="initial", scene=scene, error=None)
            )
        except (AIClientError, Exception) as exc:
            self._result_queue.put(
                WorkerResult(
                    request_id=request_id,
                    kind="initial",
                    scene=None,
                    error=f"生成初始场景失败: {exc}",
                )
            )

    def _run_settlement_request(
        self,
        request_id: int,
        premise: StoryPremise,
        settled_history_snapshot: list,
        round_actions_snapshot: list,
        scene_snapshot: SceneState,
        request_type: Literal["round_settlement", "forced_immediate_choice", "freeform_action"],
    ) -> None:
        try:
            scene = self._ai_client.settle_round(
                premise,
                scene_snapshot,
                settled_history_snapshot,
                round_actions_snapshot,
                request_type=request_type,
            )
            self._result_queue.put(
                WorkerResult(request_id=request_id, kind="settlement", scene=scene, error=None)
            )
        except (AIClientError, Exception) as exc:
            self._result_queue.put(
                WorkerResult(
                    request_id=request_id,
                    kind="settlement",
                    scene=None,
                    error=f"结算回合失败: {exc}",
                )
            )

    def _draw(self) -> None:
        self._refresh_text_input_rect()
        runtime_background = self._runtime_background()
        runtime_avatar_gender = self._runtime_avatar_gender()
        runtime_operator_name = self._runtime_operator_name()

        if self._mode == "main_menu":
            self._schedule_initial_scene_prefetch()
            self._audio.sync_menu("main_menu")
            self._menu_renderer.draw_main_menu(
                runtime_background,
                list(MAIN_MENU_OPTIONS),
                self._main_menu_index,
                self._status_text,
                operator_portrait_name=runtime_operator_name,
                operator_portrait_gender=runtime_avatar_gender,
            )
            return

        if self._mode == "story_browser":
            self._schedule_initial_scene_prefetch()
            self._audio.sync_menu("story_browser")
            self._menu_renderer.draw_story_browser(
                runtime_background,
                self.current_story,
                self.current_role,
                self._menu_selection.story_index,
                len(self._stories),
                self._story_focus,
                self._detail_modal,
                operator_portrait_name=runtime_operator_name,
                operator_portrait_gender=runtime_avatar_gender,
            )
            return

        if self._mode == "settings":
            active_editor = self._input_editor
            self._audio.sync_menu("settings")
            self._menu_renderer.draw_settings(
                runtime_background,
                list(SETTINGS_FIELDS),
                self._settings_index,
                self._settings_draft,
                None if active_editor is None else active_editor.field_name,
                "" if active_editor is None else active_editor.value,
                self._settings_status_text(),
                input_hint="" if active_editor is None else active_editor.hint_text,
                input_composition="" if active_editor is None else active_editor.composition,
                input_cursor=0 if active_editor is None else active_editor.cursor,
                input_multiline=False if active_editor is None else active_editor.multiline,
                input_secret=False if active_editor is None else active_editor.secret,
                operator_portrait_name=runtime_operator_name,
                operator_portrait_gender=runtime_avatar_gender,
            )
            return

        if self._mode == "custom_story":
            active_editor = self._input_editor
            self._audio.sync_menu("custom_story")
            self._menu_renderer.draw_custom_story_editor(
                runtime_background,
                self._custom_story_fields(),
                self._custom_story_index,
                self._custom_story_draft,
                None if active_editor is None else active_editor.field_name,
                "" if active_editor is None else active_editor.value,
                self._status_text,
                generated_story_id=self._custom_story_preview_story_id(),
                input_hint="" if active_editor is None else active_editor.hint_text,
                input_composition="" if active_editor is None else active_editor.composition,
                input_cursor=0 if active_editor is None else active_editor.cursor,
                input_multiline=False if active_editor is None else active_editor.multiline,
                input_secret=False if active_editor is None else active_editor.secret,
                operator_portrait_name=runtime_operator_name,
                operator_portrait_gender=runtime_avatar_gender,
            )
            return

        if self._session is None or self._premise is None:
            self._return_to_main_menu()
            return

        self._audio.sync_scene(self._session.current_scene)
        self._game_renderer.draw(
            self._session,
            self._ai_client.mode_label,
            self._elapsed_seconds,
            self._premise.player_display_name,
            self._premise.story_title,
            player_avatar_gender=runtime_avatar_gender,
        )

    def _enter_story_browser(self) -> None:
        self._mode = "story_browser"
        self._story_focus = "story"
        self._detail_modal = None
        self._clear_selected_text_readers()

    def _enter_settings(self) -> None:
        self._mode = "settings"
        self._settings_index = 0
        self._detail_modal = None
        self._clear_selected_text_readers()
        self._reset_settings_draft()

    def _enter_custom_story(self) -> None:
        self._mode = "custom_story"
        self._custom_story_index = 0
        self._detail_modal = None
        self._clear_selected_text_readers()
        self._reset_custom_story_draft()

    def _start_selected_story(self) -> None:
        self._detail_modal = None
        self._cancel_input_edit()
        self._clear_selected_text_readers()
        self._premise = build_story_premise(self.current_story, self.current_role.id)
        self._session = GameSessionState.create(self._premise)
        self._elapsed_seconds = 0.0
        self._mode = "game"
        cached_scene = self._ai_client.load_cached_initial_scene(self._premise)
        if cached_scene is not None:
            self._session.finish_initial_scene(cached_scene)
            self._session.record_system_text(
                "本地预生成",
                "已从本地缓存载入预生成的初始场景。",
            )
            return

        self._submit_initial_request()

    def _return_to_main_menu(self, status_text: str | None = None) -> None:
        self._request_serial += 1
        self._mode = "main_menu"
        self._session = None
        self._premise = None
        self._detail_modal = None
        self._cancel_input_edit()
        self._clear_selected_text_readers()
        if status_text is not None:
            self._status_text = status_text

    def _select_story(self, new_index: int) -> None:
        if not self._stories:
            return
        bounded = new_index % len(self._stories)
        self._menu_selection = MenuSelection(story_index=bounded, role_index=0)
        self._detail_modal = None
        self._schedule_initial_scene_prefetch()

    def _select_role(self, new_index: int) -> None:
        roles = self.current_story.roles
        bounded = new_index % len(roles)
        self._menu_selection = MenuSelection(
            story_index=self._menu_selection.story_index,
            role_index=bounded,
        )
        self._detail_modal = None
        self._schedule_initial_scene_prefetch()

    def _open_detail_modal(self) -> None:
        self._clear_selected_text_readers()
        if self._story_focus == "story":
            story = self.current_story
            self._detail_modal = DetailModal(
                title=story.title,
                subtitle=story.subtitle,
                body_lines=(
                    f"案发地点：{story.location}",
                    f"现场设定：{story.setting}",
                    f"核心案情：{story.core_case}",
                    f"开场钩子：{story.opening_hook}",
                    f"死者：{story.victim_name}｜{story.victim_identity}",
                    f"追查者：{story.detective_name}｜{story.detective_identity}",
                    "评分段位："
                    + " / ".join(f"{rank.rank}（{rank.score_range}）" for rank in story.rankings),
                ),
                footer="Enter / Space / Esc 关闭详情",
            )
            return

        role = self.current_role
        self._detail_modal = DetailModal(
            title=role.display_name,
            subtitle=f"策略类型：{role.strategy_kind} | 主工具：{role.primary_tool_name}",
            body_lines=(
                f"背景：{role.background}",
                f"动机：{role.motive}",
                f"隐藏目标：{role.hidden_objective}",
                "特殊条件：" + "；".join(role.special_conditions),
                *(f"招牌工具：{tool.name}｜{tool.description}" for tool in role.signature_tools),
            ),
            footer="Enter / Space / Esc 关闭详情",
        )

    def _commit_input_edit(self) -> None:
        editor = self._input_editor
        if editor is None:
            return

        field_name = editor.field_name
        raw_value = editor.value
        self._cancel_input_edit()

        try:
            if field_name == "__freeform_action__":
                self._submit_freeform_action(raw_value)
                return
            if self._is_custom_story_field(field_name):
                self._status_text = update_custom_story_field(
                    self._custom_story_draft,
                    field_name,
                    raw_value,
                )
                return
            if field_name == "window_title":
                value = raw_value.strip()
                if not value:
                    raise ValueError("窗口标题不能为空。")
            elif field_name == "detective_name":
                value = raw_value.strip()
                if not value:
                    raise ValueError("侦探名字不能为空。")
            elif field_name == "fps":
                value = int(raw_value.strip())
                if value < 15:
                    raise ValueError("帧率不能低于 15。")
            elif field_name == "base_url":
                value = raw_value.strip()
            elif field_name == "api_key":
                value = raw_value.strip()
            elif field_name == "model":
                value = raw_value.strip()
                if not value:
                    raise ValueError("模型名称不能为空。")
            elif field_name == "reasoning_effort":
                value = raw_value.strip().lower()
                valid_efforts = {"none", "minimal", "low", "medium", "high", "xhigh"}
                if value not in valid_efforts:
                    raise ValueError("推理强度必须是 none/minimal/low/medium/high/xhigh。")
            elif field_name == "timeout_seconds":
                value = float(raw_value.strip())
                if value <= 0:
                    raise ValueError("超时秒数必须大于 0。")
            else:
                raise ValueError(f"不支持编辑字段 {field_name!r}。")
        except ValueError as exc:
            self._status_text = str(exc)
            return

        setattr(self._settings_draft, field_name, value)
        self._status_text = f"{self._field_label(field_name)} 已更新，按 S 保存。"

    def _toggle_setting(self, field_name: str) -> None:
        current = bool(getattr(self._settings_draft, field_name))
        setattr(self._settings_draft, field_name, not current)
        self._status_text = f"{self._field_label(field_name)} 已切换，按 S 保存。"

    def _cycle_choice_setting(self, field_name: str, direction: int) -> None:
        if field_name != "avatar_gender":
            return

        current = str(getattr(self._settings_draft, field_name)).strip().lower()
        try:
            current_index = PLAYER_AVATAR_OPTIONS.index(current)
        except ValueError:
            current_index = 0
        next_index = (current_index + direction) % len(PLAYER_AVATAR_OPTIONS)
        setattr(self._settings_draft, field_name, PLAYER_AVATAR_OPTIONS[next_index])
        self._status_text = f"{self._field_label(field_name)} 已切换，按 S 保存。"

    def _save_settings(self) -> None:
        candidate = self._settings_draft.to_config(self._config)
        api_key = self._settings_draft.api_key.strip()

        if not candidate.display.title:
            self._status_text = "窗口标题不能为空。"
            return
        if not candidate.player.detective_name:
            self._status_text = "侦探名字不能为空。"
            return
        if candidate.player.avatar_gender not in PLAYER_AVATAR_OPTIONS:
            self._status_text = "主控形象必须为 male 或 female。"
            return
        if candidate.display.fps < 15:
            self._status_text = "帧率不能低于 15。"
            return
        if not candidate.ai.model:
            self._status_text = "模型名称不能为空。"
            return
        if candidate.ai.reasoning_effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
            self._status_text = "推理强度必须是 none/minimal/low/medium/high/xhigh。"
            return
        if candidate.ai.timeout_seconds <= 0:
            self._status_text = "超时秒数必须大于 0。"
            return
        if not candidate.ai.use_mock_when_unconfigured:
            if not candidate.ai.base_url:
                self._status_text = "关闭本地 Mock 前，请先填写请求 URL。"
                return
            if not api_key:
                self._status_text = "关闭本地 Mock 前，请先填写 API Key。"
                return

        try:
            save_api_key(candidate.ai.credentials_path, candidate.ai.provider, api_key)
            save_config(candidate)
        except Exception as exc:
            self._status_text = f"保存设置失败: {exc}"
            return

        self._config = candidate
        pygame.display.set_caption(candidate.display.title)
        self._settings_draft = SettingsDraft.from_config(candidate, api_key)
        self._ai_client.close()
        self._ai_client = self._build_ai_client(candidate.ai)
        self._audio.play_success("settings_saved")
        if self._status_text is None or "AI 配置不可用" not in self._status_text:
            self._status_text = "设置已保存。"

    def _reset_settings_draft(self, status_text: str | None = None) -> None:
        self._cancel_input_edit()
        self._settings_draft = SettingsDraft.from_config(
            self._config,
            load_api_key(self._config.ai.credentials_path, self._config.ai.provider),
        )
        if status_text is not None:
            self._status_text = status_text

    def _settings_status_text(self) -> str | None:
        if self._settings_dirty():
            return self._status_text or "存在未保存修改。"
        return self._status_text

    def _settings_dirty(self) -> bool:
        current = SettingsDraft.from_config(
            self._config,
            load_api_key(self._config.ai.credentials_path, self._config.ai.provider),
        )
        return self._settings_draft != current

    def _reset_custom_story_draft(self, status_text: str | None = None) -> None:
        self._cancel_input_edit()
        self._custom_story_draft = CustomStoryDraft.blank()
        self._custom_story_draft.subtitle = DEFAULT_CUSTOM_STORY_SUBTITLE
        self._custom_story_draft.detective_identity = DEFAULT_CUSTOM_DETECTIVE_IDENTITY
        self._custom_story_index = 0
        if status_text is not None:
            self._status_text = status_text

    def _save_custom_story(self) -> None:
        try:
            validate_custom_story_draft(self._custom_story_draft)
            _, story_id = write_custom_story(
                self._custom_story_draft,
                detective_name=self._runtime_operator_name(),
                stories_dir=self._stories_dir,
            )
        except ValueError as exc:
            self._status_text = str(exc)
            return
        except OSError as exc:
            self._status_text = f"保存自定义卷宗失败: {exc}"
            return

        self._stories = load_story_catalog(self._stories_dir)
        story_index = next(
            (
                index
                for index, story in enumerate(self._stories)
                if story.id == story_id
            ),
            0,
        )
        self._menu_selection = MenuSelection(story_index=story_index, role_index=0)
        self._mode = "story_browser"
        self._detail_modal = None
        self._clear_selected_text_readers()
        self._schedule_initial_scene_prefetch()
        self._audio.play_success("custom_story_saved")
        self._status_text = f"已保存自定义卷宗：{self._stories[story_index].title}"

    def _is_custom_story_field(self, field_name: str) -> bool:
        return is_custom_story_editor_key(field_name)

    def _custom_story_fields(self) -> list[CustomStoryEditorField]:
        fields = build_custom_story_editor_fields(self._custom_story_draft)
        if not fields:
            self._custom_story_index = 0
            return fields
        self._custom_story_index = min(max(self._custom_story_index, 0), len(fields) - 1)
        return fields

    def _custom_story_preview_story_id(self) -> str:
        if not self._custom_story_draft.title.strip():
            return "保存时自动生成唯一目录名"
        return "保存后会生成 stories/<自动目录>/story.json"

    def _build_ai_client(self, ai_config: AIConfig) -> ReverseDetectiveAIClient:
        try:
            return ReverseDetectiveAIClient(ai_config)
        except AIClientError as exc:
            fallback = AIConfig(
                provider=ai_config.provider,
                base_url=ai_config.base_url,
                model=ai_config.model,
                reasoning_effort=ai_config.reasoning_effort,
                timeout_seconds=ai_config.timeout_seconds,
                disable_response_storage=ai_config.disable_response_storage,
                use_mock_when_unconfigured=True,
                fallback_to_mock_on_error=True,
                credentials_path=ai_config.credentials_path,
            )
            self._status_text = f"AI 配置不可用，已临时回退到本地 Mock：{exc}"
            return ReverseDetectiveAIClient(fallback)

    def _active_text_renderer(self) -> Renderer | MenuRenderer | None:
        if self._input_editor is not None or self._detail_modal is not None:
            return None
        if self._mode == "game":
            return self._game_renderer
        if self._mode in {"main_menu", "story_browser", "settings", "custom_story"}:
            return self._menu_renderer
        return None

    def _clear_selected_text_readers(self) -> None:
        self._game_renderer.clear_selected_text()
        self._menu_renderer.clear_selected_text()

    def _schedule_initial_scene_prefetch(self, *, force: bool = False) -> None:
        if not self._can_background_prefetch_initial_scene():
            return
        premise = build_story_premise(self.current_story, self.current_role.id)
        self._ai_client.prefetch_initial_scene(premise, force=force)

    def _can_background_prefetch_initial_scene(self) -> bool:
        try:
            driver = pygame.display.get_driver()
        except pygame.error:
            return False
        return driver != "dummy"

    def _field_label(self, field_name: str) -> str:
        for candidate_name, label, _ in SETTINGS_FIELDS:
            if candidate_name == field_name:
                return label
        return field_name

    def _input_hint(self, field_name: str, field_kind: str) -> str:
        hints = {
            "window_title": "支持直接输入窗口标题。回车保存。",
            "detective_name": "支持中文输入法。回车保存名字。",
            "base_url": "输入完整请求地址，例如 https://example.com/openai 。",
            "api_key": "支持 Ctrl+V 粘贴。内容会以掩码显示。",
            "model": "输入模型名，例如 gpt-5.4 。",
            "reasoning_effort": "可用值: none / minimal / low / medium / high / xhigh。",
            "timeout_seconds": "输入大于 0 的秒数，例如 120。",
        }
        if field_kind == "secret":
            return hints.get(field_name, "支持粘贴。回车保存。")
        return hints.get(field_name, "支持输入法与方向键移动光标，回车保存。")

    def _runtime_operator_name(self) -> str:
        candidate = self._config.player.detective_name.strip()
        return candidate or self._background.operator_name

    def _runtime_avatar_gender(self) -> str:
        candidate = self._config.player.avatar_gender.strip().lower()
        if candidate in PLAYER_AVATAR_OPTIONS:
            return candidate
        return PLAYER_AVATAR_OPTIONS[0]

    def _replace_operator_name(self, text: str, *source_names: str) -> str:
        if not text:
            return text

        updated = text
        replacement = self._runtime_operator_name()
        for source_name in {name.strip() for name in source_names if name and name.strip()}:
            updated = updated.replace(source_name, replacement)
        return updated

    def _runtime_background(self) -> GameBackgroundDefinition:
        return replace(
            self._background,
            operator_name=self._runtime_operator_name(),
            background=self._replace_operator_name(
                self._background.background,
                self._background.operator_name,
            ),
            briefing=self._replace_operator_name(
                self._background.briefing,
                self._background.operator_name,
            ),
            menu_intro=self._replace_operator_name(
                self._background.menu_intro,
                self._background.operator_name,
            ),
        )

    def _runtime_story(self, story: StoryDefinition) -> StoryDefinition:
        operator_name = self._runtime_operator_name()
        return replace(
            story,
            simulation_operator_name=operator_name,
            simulation_background=self._replace_operator_name(
                story.simulation_background,
                story.simulation_operator_name,
                self._background.operator_name,
                story.detective_name,
            ),
            simulation_briefing=self._replace_operator_name(
                story.simulation_briefing,
                story.simulation_operator_name,
                self._background.operator_name,
                story.detective_name,
            ),
            opening_hook=self._replace_operator_name(
                story.opening_hook,
                story.detective_name,
                story.simulation_operator_name,
                self._background.operator_name,
            ),
            detective_name=operator_name,
        )

    @property
    def current_story(self) -> StoryDefinition:
        return self._runtime_story(self._stories[self._menu_selection.story_index])

    @property
    def current_role(self) -> StoryRole:
        return self.current_story.roles[self._menu_selection.role_index]


def run_game() -> None:
    """Run the Pygame demo."""

    app = GameApp(load_config())
    app.run()


def main() -> None:
    """CLI script entrypoint."""

    run_game()
