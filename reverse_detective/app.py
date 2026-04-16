"""Application entrypoint for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
import threading
from typing import Literal

import pygame

from reverse_detective.ai_client import AIClientError, ReverseDetectiveAIClient
from reverse_detective.config import (
    AIConfig,
    AppConfig,
    DisplayConfig,
    load_api_key,
    load_config,
    save_api_key,
    save_config,
)
from reverse_detective.game_state import GameSessionState, PendingChoice
from reverse_detective.models import (
    GameBackgroundDefinition,
    Interactable,
    SceneState,
    StoryDefinition,
    StoryPremise,
    StoryRole,
)
from reverse_detective.renderer import MenuRenderer, Renderer
from reverse_detective.story_loader import build_story_premise, load_game_background, load_story_catalog


PLAY_AREA_HEIGHT = 520
PLAYER_SIZE = (42, 62)
PLAYER_SPEED = 240.0
MAIN_MENU_OPTIONS = ("开始游戏", "选项设置", "退出游戏")
SETTINGS_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("window_title", "窗口标题", "text"),
    ("fps", "帧率 FPS", "int"),
    ("base_url", "请求 Base URL", "text"),
    ("api_key", "API Key", "secret"),
    ("model", "模型名称", "text"),
    ("timeout_seconds", "超时秒数", "float"),
    ("use_mock_when_unconfigured", "未配置时使用本地 Mock", "bool"),
    ("fallback_to_mock_on_error", "请求失败时回退 Mock", "bool"),
)

MenuMode = Literal["main_menu", "story_browser", "settings", "game"]
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
    fps: int
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    use_mock_when_unconfigured: bool
    fallback_to_mock_on_error: bool

    @classmethod
    def from_config(cls, config: AppConfig, api_key: str) -> "SettingsDraft":
        return cls(
            window_title=config.display.title,
            fps=config.display.fps,
            base_url=config.ai.base_url,
            api_key=api_key,
            model=config.ai.model,
            timeout_seconds=config.ai.timeout_seconds,
            use_mock_when_unconfigured=config.ai.use_mock_when_unconfigured,
            fallback_to_mock_on_error=config.ai.fallback_to_mock_on_error,
        )

    def to_config(self, current_config: AppConfig) -> AppConfig:
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
                timeout_seconds=self.timeout_seconds,
                use_mock_when_unconfigured=self.use_mock_when_unconfigured,
                fallback_to_mock_on_error=self.fallback_to_mock_on_error,
                credentials_path=current_config.ai.credentials_path,
            ),
        )


class GameApp:
    """Main game application with menu flow, settings and background scene generation."""

    def __init__(self, config: AppConfig):
        self._config = config
        self._background: GameBackgroundDefinition = load_game_background()
        self._stories = load_story_catalog()
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
        self._editing_field: str | None = None
        self._input_buffer = ""
        self._status_text: str | None = None
        self._settings_draft = SettingsDraft.from_config(
            config,
            load_api_key(config.ai.credentials_path, config.ai.provider),
        )

        pygame.init()
        pygame.display.set_caption(config.display.title)
        self._screen = pygame.display.set_mode((config.display.width, config.display.height))
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
        self._ai_client = self._build_ai_client(config.ai)

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
            pygame.quit()

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_keydown(event.key, getattr(event, "unicode", ""))

    def _handle_keydown(self, key: int, text: str = "") -> None:
        if self._editing_field is not None:
            self._handle_input_keydown(key, text)
            return

        if self._detail_modal is not None:
            if key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE, pygame.K_BACKSPACE):
                self._detail_modal = None
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

        self._handle_game_keydown(key)

    def _handle_main_menu_keydown(self, key: int) -> None:
        if key == pygame.K_UP:
            self._main_menu_index = (self._main_menu_index - 1) % len(MAIN_MENU_OPTIONS)
            return

        if key == pygame.K_DOWN:
            self._main_menu_index = (self._main_menu_index + 1) % len(MAIN_MENU_OPTIONS)
            return

        if key not in (pygame.K_RETURN, pygame.K_SPACE):
            return

        if self._main_menu_index == 0:
            self._enter_story_browser()
        elif self._main_menu_index == 1:
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
            self._open_detail_modal()
            return

        if key == pygame.K_SPACE:
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

        if key in (pygame.K_LEFT, pygame.K_RIGHT) and field_kind == "bool":
            self._toggle_setting(field_name)
            return

        if key == pygame.K_RETURN:
            if field_kind == "bool":
                self._toggle_setting(field_name)
            else:
                self._editing_field = field_name
                self._input_buffer = str(getattr(self._settings_draft, field_name))
            return

        if key == pygame.K_s:
            self._save_settings()
            return

        if key == pygame.K_d:
            self._reset_settings_draft("已放弃未保存的修改")

    def _handle_input_keydown(self, key: int, text: str) -> None:
        if self._editing_field is None:
            return

        if key == pygame.K_ESCAPE:
            self._editing_field = None
            self._input_buffer = ""
            self._status_text = "已取消输入"
            return

        if key == pygame.K_RETURN:
            self._commit_input_edit()
            return

        if key == pygame.K_BACKSPACE:
            self._input_buffer = self._input_buffer[:-1]
            return

        if text and text.isprintable() and len(self._input_buffer) < 240:
            self._input_buffer += text

    def _handle_game_keydown(self, key: int) -> None:
        if key == pygame.K_m:
            self._return_to_main_menu("已返回主菜单")
            return

        if key == pygame.K_r:
            self._submit_initial_request()
            return

        if self._mode != "game" or self._session is None or self._session.loading:
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
                self._submit_action_request(choice)
            return

        if pygame.K_1 <= key <= pygame.K_9:
            option_index = key - pygame.K_1
            choice = self._session.choose_option_by_index(option_index)
            if choice is not None:
                self._submit_action_request(choice)

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
            else:
                self._session.finish_action(result.scene)

    def _update_active_interactable(self) -> None:
        if self._mode != "game" or self._session is None:
            return

        if self._session.loading or self._session.current_scene.is_terminal:
            self._session.set_active_interactable(None)
            return

        player_rect = self._player_rect()
        best_match: tuple[float, str] | None = None

        for interactable in self._session.current_scene.interactables:
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
        self._session.begin_action()
        premise_snapshot = self._premise
        worker = threading.Thread(
            target=self._run_initial_request,
            args=(request_id, premise_snapshot),
            daemon=True,
        )
        worker.start()

    def _submit_action_request(self, choice: PendingChoice) -> None:
        if self._session is None or self._premise is None or self._session.loading:
            return

        self._request_serial += 1
        request_id = self._request_serial
        history_snapshot = list(self._session.action_history)
        scene_snapshot = self._session.current_scene
        premise_snapshot = self._premise
        self._session.begin_action(choice)
        worker = threading.Thread(
            target=self._run_action_request,
            args=(request_id, premise_snapshot, history_snapshot, scene_snapshot, choice),
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

    def _run_action_request(
        self,
        request_id: int,
        premise: StoryPremise,
        history_snapshot: list,
        scene_snapshot: SceneState,
        choice: PendingChoice,
    ) -> None:
        try:
            scene = self._ai_client.generate_next_scene(
                premise,
                scene_snapshot,
                history_snapshot,
                choice,
            )
            self._result_queue.put(
                WorkerResult(request_id=request_id, kind="action", scene=scene, error=None)
            )
        except (AIClientError, Exception) as exc:
            self._result_queue.put(
                WorkerResult(
                    request_id=request_id,
                    kind="action",
                    scene=None,
                    error=f"推进场景失败: {exc}",
                )
            )

    def _draw(self) -> None:
        if self._mode == "main_menu":
            self._menu_renderer.draw_main_menu(
                self._background,
                list(MAIN_MENU_OPTIONS),
                self._main_menu_index,
                self._status_text,
            )
            return

        if self._mode == "story_browser":
            self._menu_renderer.draw_story_browser(
                self._background,
                self.current_story,
                self.current_role,
                self._menu_selection.story_index,
                len(self._stories),
                self._story_focus,
                self._detail_modal,
            )
            return

        if self._mode == "settings":
            self._menu_renderer.draw_settings(
                self._background,
                list(SETTINGS_FIELDS),
                self._settings_index,
                self._settings_draft,
                self._editing_field,
                self._input_buffer,
                self._settings_status_text(),
            )
            return

        if self._session is None or self._premise is None:
            self._return_to_main_menu()
            return

        self._game_renderer.draw(
            self._session,
            self._ai_client.mode_label,
            self._elapsed_seconds,
            self._premise.player_display_name,
            self._premise.story_title,
        )

    def _enter_story_browser(self) -> None:
        self._mode = "story_browser"
        self._story_focus = "story"
        self._detail_modal = None

    def _enter_settings(self) -> None:
        self._mode = "settings"
        self._settings_index = 0
        self._detail_modal = None
        self._reset_settings_draft()

    def _start_selected_story(self) -> None:
        self._detail_modal = None
        self._editing_field = None
        self._input_buffer = ""
        self._premise = build_story_premise(self.current_story, self.current_role.id)
        self._session = GameSessionState.create(self._premise)
        self._elapsed_seconds = 0.0
        self._mode = "game"
        self._submit_initial_request()

    def _return_to_main_menu(self, status_text: str | None = None) -> None:
        self._request_serial += 1
        self._mode = "main_menu"
        self._session = None
        self._premise = None
        self._detail_modal = None
        self._editing_field = None
        self._input_buffer = ""
        if status_text is not None:
            self._status_text = status_text

    def _select_story(self, new_index: int) -> None:
        if not self._stories:
            return
        bounded = new_index % len(self._stories)
        self._menu_selection = MenuSelection(story_index=bounded, role_index=0)
        self._detail_modal = None

    def _select_role(self, new_index: int) -> None:
        roles = self.current_story.roles
        bounded = new_index % len(roles)
        self._menu_selection = MenuSelection(
            story_index=self._menu_selection.story_index,
            role_index=bounded,
        )
        self._detail_modal = None

    def _open_detail_modal(self) -> None:
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
                    f"死者：{story.victim_name}，{story.victim_identity}",
                    f"追查者：{story.detective_name}，{story.detective_identity}",
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
                *(f"招牌工具：{tool.name}，{tool.description}" for tool in role.signature_tools),
            ),
            footer="Enter / Space / Esc 关闭详情",
        )

    def _commit_input_edit(self) -> None:
        if self._editing_field is None:
            return

        field_name = self._editing_field
        raw_value = self._input_buffer
        self._editing_field = None
        self._input_buffer = ""

        try:
            if field_name == "window_title":
                value = raw_value.strip()
                if not value:
                    raise ValueError("窗口标题不能为空。")
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

    def _save_settings(self) -> None:
        candidate = self._settings_draft.to_config(self._config)
        api_key = self._settings_draft.api_key.strip()

        if not candidate.display.title:
            self._status_text = "窗口标题不能为空。"
            return
        if candidate.display.fps < 15:
            self._status_text = "帧率不能低于 15。"
            return
        if not candidate.ai.model:
            self._status_text = "模型名称不能为空。"
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
        self._ai_client = self._build_ai_client(candidate.ai)
        if self._status_text is None or "AI 配置不可用" not in self._status_text:
            self._status_text = "设置已保存。"

    def _reset_settings_draft(self, status_text: str | None = None) -> None:
        self._editing_field = None
        self._input_buffer = ""
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

    def _build_ai_client(self, ai_config: AIConfig) -> ReverseDetectiveAIClient:
        try:
            return ReverseDetectiveAIClient(ai_config)
        except AIClientError as exc:
            fallback = AIConfig(
                provider=ai_config.provider,
                base_url=ai_config.base_url,
                model=ai_config.model,
                timeout_seconds=ai_config.timeout_seconds,
                use_mock_when_unconfigured=True,
                fallback_to_mock_on_error=True,
                credentials_path=ai_config.credentials_path,
            )
            self._status_text = f"AI 配置不可用，已临时回退到本地 Mock：{exc}"
            return ReverseDetectiveAIClient(fallback)

    def _field_label(self, field_name: str) -> str:
        for candidate_name, label, _ in SETTINGS_FIELDS:
            if candidate_name == field_name:
                return label
        return field_name

    @property
    def current_story(self) -> StoryDefinition:
        return self._stories[self._menu_selection.story_index]

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
