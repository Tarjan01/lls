"""Helpers for resolving image assets from the local library."""

from __future__ import annotations

from collections.abc import Iterable
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_ASSET_LIBRARY_ROOT = Path("assets/img").resolve()
# Backward-compatible alias for older imports.
DEFAULT_ASSET_CACHE_ROOT = DEFAULT_ASSET_LIBRARY_ROOT

_VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_KIND_DIRECTORIES = {
    "background": "backgrounds",
    "npc": "npcs",
    "interactable": "interactables",
}
_KIND_LIBRARY_FILENAMES = {
    "background": Path("backgrounds/library.json"),
}
_CATALOG_FILENAME = "catalog.json"
_CATALOG_CACHE: dict[Path, dict[str, list[dict[str, Any]]]] = {}
_KIND_LIBRARY_CACHE: dict[tuple[Path, str], list[dict[str, Any]]] = {}
_MIN_CATALOG_MATCH_SCORE = 20.0


def resolve_asset_path(
    asset_kind: str,
    asset_ref: str,
    asset_root: Path | None = None,
    *hint_texts: str,
) -> Path | None:
    """Resolve an asset reference to the closest local asset path."""

    cleaned_ref = asset_ref.strip()
    if not cleaned_ref:
        return None

    direct_path = Path(cleaned_ref).expanduser()
    if direct_path.is_file():
        return direct_path.resolve()

    root = (asset_root or DEFAULT_ASSET_LIBRARY_ROOT).resolve()
    candidate_direct = root / cleaned_ref
    if candidate_direct.is_file():
        return candidate_direct.resolve()

    kind_directory = _KIND_DIRECTORIES.get(asset_kind, asset_kind)
    candidate_by_name = root / kind_directory / _sanitize_asset_filename(direct_path.name or cleaned_ref)
    if candidate_by_name.is_file():
        return candidate_by_name.resolve()

    library_match = _resolve_from_kind_library(root, asset_kind, cleaned_ref, hint_texts)
    if library_match is not None:
        return library_match

    catalog_match = _resolve_from_catalog(root, asset_kind, cleaned_ref, hint_texts)
    if catalog_match is not None:
        return catalog_match

    if asset_kind == "background":
        fallback_background = _resolve_default_background(root)
        if fallback_background is not None:
            return fallback_background

    return candidate_by_name


def resolve_cached_asset_path(
    asset_kind: str,
    asset_ref: str,
    asset_root: Path | None = None,
    *hint_texts: str,
) -> Path | None:
    """Backward-compatible wrapper around :func:`resolve_asset_path`."""

    return resolve_asset_path(asset_kind, asset_ref, asset_root, *hint_texts)


def ensure_asset_parent(path: Path) -> Path:
    """Ensure the parent directory exists before writing or copying an asset."""

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_from_catalog(
    root: Path,
    asset_kind: str,
    asset_ref: str,
    hint_texts: Iterable[str],
) -> Path | None:
    catalog = _load_catalog(root)
    entries = catalog.get(asset_kind, [])
    return _resolve_from_entries(root, entries, asset_ref, hint_texts)


def _resolve_from_kind_library(
    root: Path,
    asset_kind: str,
    asset_ref: str,
    hint_texts: Iterable[str],
) -> Path | None:
    entries = _load_kind_library(root, asset_kind)
    return _resolve_from_entries(root, entries, asset_ref, hint_texts)


def _resolve_from_entries(
    root: Path,
    entries: Iterable[dict[str, Any]],
    asset_ref: str,
    hint_texts: Iterable[str],
) -> Path | None:
    if not entries:
        return None

    query_text = " ".join(fragment for fragment in (asset_ref, *hint_texts) if fragment).strip()
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

        score = _score_catalog_entry(entry, query_normalized, query_tokens)
        if score > best_score:
            best_score = score
            best_path = entry_path

    if best_score < _MIN_CATALOG_MATCH_SCORE:
        return None
    return best_path


def _resolve_default_background(root: Path) -> Path | None:
    entries = _load_kind_library(root, "background")
    if not entries:
        return None

    default_candidates: list[Path] = []
    fallback_candidates: list[Path] = []
    for entry in entries:
        relative_path = entry.get("path")
        if not isinstance(relative_path, str) or not relative_path.strip():
            continue

        entry_path = (root / relative_path).resolve()
        if not entry_path.is_file():
            continue

        fallback_candidates.append(entry_path)
        markers = {
            _normalize_text(str(entry.get("id", ""))),
            *(_normalize_text(value) for value in _as_string_list(entry.get("aliases"))),
            *(_normalize_text(value) for value in _as_string_list(entry.get("tags"))),
        }
        if "default" in markers:
            default_candidates.append(entry_path)

    if default_candidates:
        return default_candidates[0]
    if fallback_candidates:
        return fallback_candidates[0]
    return None


def _score_catalog_entry(
    entry: dict[str, Any],
    query_normalized: str,
    query_tokens: set[str],
) -> float:
    entry_id = _normalize_text(str(entry.get("id", "")))
    entry_path_stem = _normalize_text(Path(str(entry.get("path", ""))).stem)
    aliases = [_normalize_text(value) for value in _as_string_list(entry.get("aliases"))]
    tags = [_normalize_text(value) for value in _as_string_list(entry.get("tags"))]
    candidates = [value for value in [entry_id, entry_path_stem, *aliases, *tags] if value]
    if not candidates:
        return 0.0

    score = 0.0
    if query_normalized:
        if query_normalized in candidates:
            score += 120.0
        if entry_id and query_normalized == entry_id:
            score += 80.0
        if entry_path_stem and query_normalized == entry_path_stem:
            score += 70.0
        for candidate in candidates:
            if query_normalized and query_normalized in candidate:
                score += 16.0
            if candidate and candidate in query_normalized:
                score += 10.0
            score += SequenceMatcher(None, query_normalized, candidate).ratio() * 18.0

    if query_tokens:
        entry_tokens = set().union(*(_tokenize(candidate) for candidate in candidates))
        overlap = query_tokens & entry_tokens
        score += len(overlap) * 18.0
        if overlap:
            score += 12.0 * (len(overlap) / max(len(query_tokens), 1))

    return score


def _load_catalog(root: Path) -> dict[str, list[dict[str, Any]]]:
    cached = _CATALOG_CACHE.get(root)
    if cached is not None:
        return cached

    catalog_path = root / _CATALOG_FILENAME
    if not catalog_path.is_file():
        _CATALOG_CACHE[root] = {}
        return {}

    try:
        raw_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _CATALOG_CACHE[root] = {}
        return {}

    if not isinstance(raw_catalog, dict):
        _CATALOG_CACHE[root] = {}
        return {}

    normalized_catalog: dict[str, list[dict[str, Any]]] = {}
    for kind, entries in raw_catalog.items():
        if not isinstance(kind, str) or not isinstance(entries, list):
            continue
        normalized_entries = [entry for entry in entries if isinstance(entry, dict)]
        normalized_catalog[kind] = normalized_entries

    _CATALOG_CACHE[root] = normalized_catalog
    return normalized_catalog


def _load_kind_library(root: Path, asset_kind: str) -> list[dict[str, Any]]:
    cache_key = (root, asset_kind)
    cached = _KIND_LIBRARY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    relative_path = _KIND_LIBRARY_FILENAMES.get(asset_kind)
    if relative_path is None:
        _KIND_LIBRARY_CACHE[cache_key] = []
        return []

    library_path = root / relative_path
    if not library_path.is_file():
        _KIND_LIBRARY_CACHE[cache_key] = []
        return []

    try:
        raw_payload = json.loads(library_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _KIND_LIBRARY_CACHE[cache_key] = []
        return []

    if isinstance(raw_payload, dict):
        raw_entries = raw_payload.get("entries", [])
    else:
        raw_entries = raw_payload

    if not isinstance(raw_entries, list):
        _KIND_LIBRARY_CACHE[cache_key] = []
        return []

    entries = [entry for entry in raw_entries if isinstance(entry, dict)]
    _KIND_LIBRARY_CACHE[cache_key] = entries
    return entries


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _sanitize_asset_filename(asset_ref: str) -> str:
    raw_name = Path(asset_ref).name.strip() or "asset"
    stem = Path(raw_name).stem or "asset"
    suffix = Path(raw_name).suffix.lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem).strip("_").lower() or "asset"
    if suffix not in _VALID_EXTENSIONS:
        suffix = ".png"
    return f"{safe_stem}{suffix}"


def _normalize_text(value: str) -> str:
    return " ".join(sorted(_tokenize(value)))


def _tokenize(value: str) -> set[str]:
    lowered = value.lower().replace(".png", " ").replace(".jpg", " ").replace(".webp", " ")
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
