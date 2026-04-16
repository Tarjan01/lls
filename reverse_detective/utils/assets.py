"""Helpers for resolving runtime-generated image assets."""

from __future__ import annotations

from pathlib import Path
import re


DEFAULT_ASSET_CACHE_ROOT = Path(".runtime_assets").resolve()

_VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_KIND_DIRECTORIES = {
    "background": "backgrounds",
    "npc": "npcs",
    "interactable": "interactables",
}


def resolve_cached_asset_path(
    asset_kind: str,
    asset_ref: str,
    asset_root: Path | None = None,
) -> Path | None:
    """Resolve an asset reference to its runtime cache path."""

    cleaned_ref = asset_ref.strip()
    if not cleaned_ref:
        return None

    direct_path = Path(cleaned_ref).expanduser()
    if direct_path.is_file():
        return direct_path.resolve()

    root = (asset_root or DEFAULT_ASSET_CACHE_ROOT).resolve()
    kind_directory = _KIND_DIRECTORIES.get(asset_kind, asset_kind)
    return root / kind_directory / _sanitize_asset_filename(direct_path.name or cleaned_ref)


def ensure_asset_parent(path: Path) -> Path:
    """Ensure the runtime asset directory exists before writing."""

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _sanitize_asset_filename(asset_ref: str) -> str:
    raw_name = Path(asset_ref).name.strip() or "generated_asset"
    stem = Path(raw_name).stem or "generated_asset"
    suffix = Path(raw_name).suffix.lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem).strip("_").lower() or "generated_asset"
    if suffix not in _VALID_EXTENSIONS:
        suffix = ".png"
    return f"{safe_stem}{suffix}"
