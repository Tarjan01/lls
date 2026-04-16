"""Application entrypoint for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
import threading

import pygame

from reverse_detective.ai_client import AIClientError, ReverseDetectiveAIClient, build_default_premise
from reverse_detective.config import AppConfig, load_config
from reverse_detective.game_state import GameSessionState, PendingChoice
from reverse_detective.models import Interactable, SceneState
from reverse_detective.renderer import Renderer


PLAY_AREA_HEIGHT = 520
PLAYER_SIZE = (42, 62)
PLAYER_SPEED = 240.0


@dataclass(frozen=True, slots=True)
class WorkerResult:
    request_id: int
    kind: str
    scene: SceneState | None
    error: str | None


class GameApp:
    """Main game application with background scene generation."""

    def __init__(self, config: AppConfig):
        self._config = config
        self._premise = build_default_premise()
        self._session = GameSessionState.create(self._premise)
        self._result_queue: Queue[WorkerResult] = Queue()
        self._elapsed_seconds = 0.0
        self._running = True
        self._request_serial = 0

        pygame.init()
        pygame.display.set_caption(config.display.title)
        self._screen = pygame.display.set_mode((config.display.width, config.display.height))
        self._clock = pygame.time.Clock()
        self._renderer = Renderer(
            self._screen,
            config.display.width,
            config.display.height,
            PLAY_AREA_HEIGHT,
        )
        self._ai_client = ReverseDetectiveAIClient(config.ai)

        self._submit_initial_request()

    def run(self) -> None:
        try:
            while self._running:
                delta_time = self._clock.tick(self._config.display.fps) / 1000
                self._elapsed_seconds += delta_time

                self._handle_events()
                self._update_movement(delta_time)
                self._poll_worker_results()
                self._update_active_interactable()
                self._renderer.draw(self._session, self._ai_client.mode_label, self._elapsed_seconds)
        finally:
            pygame.quit()

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_keydown(event.key)

    def _handle_keydown(self, key: int) -> None:
        if key == pygame.K_ESCAPE:
            self._running = False
            return

        if key == pygame.K_r:
            self._submit_initial_request()
            return

        if self._session.loading:
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
        self._request_serial += 1
        request_id = self._request_serial
        self._session.reset_for_restart()
        self._session.begin_action()
        worker = threading.Thread(target=self._run_initial_request, args=(request_id,), daemon=True)
        worker.start()

    def _submit_action_request(self, choice: PendingChoice) -> None:
        if self._session.loading:
            return

        self._request_serial += 1
        request_id = self._request_serial
        history_snapshot = list(self._session.action_history)
        scene_snapshot = self._session.current_scene
        self._session.begin_action(choice)
        worker = threading.Thread(
            target=self._run_action_request,
            args=(request_id, history_snapshot, scene_snapshot, choice),
            daemon=True,
        )
        worker.start()

    def _run_initial_request(self, request_id: int) -> None:
        try:
            scene = self._ai_client.generate_initial_scene(self._premise)
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
        history_snapshot: list,
        scene_snapshot: SceneState,
        choice: PendingChoice,
    ) -> None:
        try:
            scene = self._ai_client.generate_next_scene(
                self._premise,
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


def run_game() -> None:
    """Run the Pygame demo."""

    app = GameApp(load_config())
    app.run()


def main() -> None:
    """CLI script entrypoint."""

    run_game()
