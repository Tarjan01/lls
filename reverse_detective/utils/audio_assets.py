"""Helpers for resolving local audio cues from the bundled library."""

from __future__ import annotations

from collections.abc import Iterable
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_AUDIO_LIBRARY_ROOT = Path("assets/audio").resolve()
_KIND_LIBRARY_FILENAMES = {
    "bgm": Path("bgm/library.json"),
    "sfx": Path("sfx/library.json"),
}
_VALID_EXTENSIONS = {".ogg", ".mp3", ".wav"}
_MIN_AUDIO_MATCH_SCORE = 18.0
_LIBRARY_CACHE: dict[tuple[Path, str], list[dict[str, Any]]] = {}
_SILENCE_MARKERS = {"", "none", "null", "silence", "silence.mp3", "mute"}


def resolve_audio_path(
    audio_kind: str,
    audio_ref: str | None,
    audio_root: Path | None = None,
    *hint_texts: str,
) -> Path | None:
    """Resolve an audio cue id or filename to a local audio path."""

    cleaned_ref = "" if audio_ref is None else str(audio_ref).strip()
    if cleaned_ref.lower() in _SILENCE_MARKERS:
        return None

    root = (audio_root or DEFAULT_AUDIO_LIBRARY_ROOT).resolve()
    direct_path = Path(cleaned_ref).expanduser()
    if direct_path.is_file():
        return direct_path.resolve()

    candidate_direct = root / cleaned_ref
    if candidate_direct.is_file():
        return candidate_direct.resolve()

    candidate_by_name = root / audio_kind / _sanitize_audio_filename(cleaned_ref)
    if candidate_by_name.is_file():
        return candidate_by_name.resolve()

    entries = _load_library(root, audio_kind)
    return _resolve_from_entries(root, entries, cleaned_ref, hint_texts)


def _load_library(root: Path, audio_kind: str) -> list[dict[str, Any]]:
    cache_key = (root, audio_kind)
    cached = _LIBRARY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    relative_path = _KIND_LIBRARY_FILENAMES.get(audio_kind)
    if relative_path is None:
        _LIBRARY_CACHE[cache_key] = []
        return []

    library_path = root / relative_path
    if not library_path.is_file():
        _LIBRARY_CACHE[cache_key] = []
        return []

    try:
        raw_payload = json.loads(library_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _LIBRARY_CACHE[cache_key] = []
        return []

    raw_entries = raw_payload.get("entries", raw_payload) if isinstance(raw_payload, dict) else raw_payload
    if not isinstance(raw_entries, list):
        _LIBRARY_CACHE[cache_key] = []
        return []

    entries = [entry for entry in raw_entries if isinstance(entry, dict)]
    _LIBRARY_CACHE[cache_key] = entries
    return entries


def _resolve_from_entries(
    root: Path,
    entries: Iterable[dict[str, Any]],
    audio_ref: str,
    hint_texts: Iterable[str],
) -> Path | None:
    query_text = " ".join(fragment for fragment in (audio_ref, *hint_texts) if fragment).strip()
    query_normalized = _normalize_text(query_text)
    query_tokens = _tokenize(query_text)
    if not query_normalized and not query_tokens:
        return None

    best_score = 0.0
    best_path: Path | None = None
    for entry in entries:
        relative_path = entry.get("path")
        if not isinstance(relative_path, str) or not relative_path.strip():
            continue

        entry_path = (root / relative_path).resolve()
        if not entry_path.is_file():
            continue

        score = _score_entry(entry, query_normalized, query_tokens)
        if score > best_score:
            best_score = score
            best_path = entry_path

    if best_score < _MIN_AUDIO_MATCH_SCORE:
        return None
    return best_path


def _score_entry(entry: dict[str, Any], query_normalized: str, query_tokens: set[str]) -> float:
    entry_id = _normalize_text(str(entry.get("id", "")))
    entry_stem = _normalize_text(Path(str(entry.get("path", ""))).stem)
    aliases = [_normalize_text(value) for value in _as_string_list(entry.get("aliases"))]
    tags = [_normalize_text(value) for value in _as_string_list(entry.get("tags"))]
    candidates = [value for value in [entry_id, entry_stem, *aliases, *tags] if value]
    if not candidates:
        return 0.0

    score = 0.0
    if query_normalized:
        if query_normalized in candidates:
            score += 120.0
        for candidate in candidates:
            if query_normalized in candidate:
                score += 18.0
            if candidate in query_normalized:
                score += 10.0
            score += SequenceMatcher(None, query_normalized, candidate).ratio() * 18.0

    if query_tokens:
        entry_tokens = set().union(*(_tokenize(candidate) for candidate in candidates))
        overlap = query_tokens & entry_tokens
        score += len(overlap) * 16.0
        if overlap:
            score += 8.0 * (len(overlap) / max(len(query_tokens), 1))
    return score


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _sanitize_audio_filename(audio_ref: str) -> str:
    raw_name = Path(audio_ref).name.strip() or "audio"
    stem = Path(raw_name).stem or "audio"
    suffix = Path(raw_name).suffix.lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem).strip("_").lower() or "audio"
    if suffix not in _VALID_EXTENSIONS:
        suffix = ".ogg"
    return f"{safe_stem}{suffix}"


def _normalize_text(value: str) -> str:
    return " ".join(sorted(_tokenize(value)))


def _tokenize(value: str) -> set[str]:
    lowered = (
        value.lower()
        .replace(".ogg", " ")
        .replace(".mp3", " ")
        .replace(".wav", " ")
    )
    tokens = {token for token in re.split(r"[^a-z0-9]+", lowered) if token}

    for run in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", value):
        cleaned = run.strip()
        if not cleaned:
            continue
        tokens.add(cleaned)
        for width in (2, 3):
            if len(cleaned) < width:
                continue
            for index in range(len(cleaned) - width + 1):
                tokens.add(cleaned[index : index + width])

    return tokens

