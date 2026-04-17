from __future__ import annotations

from pathlib import Path

from reverse_detective.utils.audio_assets import resolve_audio_path


ASSET_ROOT = Path("assets/audio").resolve()


def test_resolve_audio_path_matches_known_bgm_cue() -> None:
    resolved = resolve_audio_path("bgm", "tense_loop", ASSET_ROOT)

    assert resolved is not None
    assert resolved.name == "tense_loop.ogg"


def test_resolve_audio_path_matches_suspense_bgm_cue() -> None:
    resolved = resolve_audio_path("bgm", "crime_suspense_high", ASSET_ROOT)

    assert resolved is not None
    assert resolved.name == "crime_suspense_high.wav"


def test_resolve_audio_path_matches_chinese_sound_hint() -> None:
    resolved = resolve_audio_path("sfx", "开锁", ASSET_ROOT, "unlock_door")

    assert resolved is not None
    assert resolved.name == "lock_open.ogg"


def test_resolve_audio_path_returns_none_for_silence_markers() -> None:
    assert resolve_audio_path("bgm", "silence", ASSET_ROOT) is None
    assert resolve_audio_path("sfx", None, ASSET_ROOT) is None
