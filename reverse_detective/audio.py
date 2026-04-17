"""Runtime audio playback for bundled BGM and sound effects."""

from __future__ import annotations

from pathlib import Path

import pygame

from reverse_detective.models import SceneState
from reverse_detective.utils.audio_assets import DEFAULT_AUDIO_LIBRARY_ROOT, resolve_audio_path


MENU_BGM_CUE = "menu_mystery"
SETTINGS_BGM_CUE = "menu_mystery"
STORY_BROWSER_BGM_CUE = "menu_mystery"
DEFAULT_CONFIRM_SFX = "ui_confirm"
DEFAULT_SUCCESS_SFX = "ui_success"


class AudioController:
    """Thin wrapper around pygame.mixer with cue-based asset resolution."""

    def __init__(self, audio_root: Path | None = None) -> None:
        self._audio_root = (audio_root or DEFAULT_AUDIO_LIBRARY_ROOT).resolve()
        self._music_path: Path | None = None
        self._sound_cache: dict[Path, pygame.mixer.Sound] = {}
        self._enabled = self._init_mixer()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def close(self) -> None:
        if not self._enabled:
            return
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            return

    def sync_menu(self, menu_kind: str) -> None:
        cue = {
            "main_menu": MENU_BGM_CUE,
            "settings": SETTINGS_BGM_CUE,
            "story_browser": STORY_BROWSER_BGM_CUE,
            "custom_story": MENU_BGM_CUE,
        }.get(menu_kind, MENU_BGM_CUE)
        self._play_music(cue, menu_kind)

    def sync_scene(self, scene: SceneState) -> None:
        self._play_music(
            scene.scene.bgm,
            scene.scene.bgm_tension,
            scene.scene.description,
            scene.narrative,
        )

    def play_effect(self, effect_ref: str | None, *hint_texts: str) -> None:
        if not self._enabled:
            return
        sound_path = resolve_audio_path("sfx", effect_ref, self._audio_root, *hint_texts)
        if sound_path is None:
            return
        sound = self._load_sound(sound_path)
        if sound is None:
            return
        sound.set_volume(0.7)
        try:
            sound.play()
        except pygame.error:
            return

    def play_confirm(self, *hint_texts: str) -> None:
        self.play_effect(DEFAULT_CONFIRM_SFX, *hint_texts)

    def play_success(self, *hint_texts: str) -> None:
        self.play_effect(DEFAULT_SUCCESS_SFX, *hint_texts)

    def _play_music(self, cue_ref: str | None, *hint_texts: str) -> None:
        if not self._enabled:
            return
        music_path = resolve_audio_path("bgm", cue_ref, self._audio_root, *hint_texts)
        if music_path == self._music_path:
            return
        try:
            if music_path is None:
                pygame.mixer.music.stop()
                self._music_path = None
                return

            pygame.mixer.music.load(str(music_path))
            pygame.mixer.music.set_volume(0.45)
            pygame.mixer.music.play(-1)
            self._music_path = music_path
        except pygame.error:
            self._music_path = None

    def _init_mixer(self) -> bool:
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init()
        except pygame.error:
            return False
        return pygame.mixer.get_init() is not None

    def _load_sound(self, sound_path: Path) -> pygame.mixer.Sound | None:
        cached = self._sound_cache.get(sound_path)
        if cached is not None:
            return cached
        try:
            sound = pygame.mixer.Sound(str(sound_path))
        except pygame.error:
            return None
        self._sound_cache[sound_path] = sound
        return sound
