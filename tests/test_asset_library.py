from __future__ import annotations

import json
from pathlib import Path

from reverse_detective.utils.assets import DEFAULT_ASSET_LIBRARY_ROOT, resolve_asset_path


def test_resolve_asset_path_matches_catalog_alias(tmp_path: Path) -> None:
    background_dir = tmp_path / "backgrounds"
    background_dir.mkdir(parents=True)
    asset_path = background_dir / "security_control_room.png"
    asset_path.write_bytes(b"png")

    catalog = {
        "background": [
            {
                "id": "security_control_room",
                "path": "backgrounds/security_control_room.png",
                "aliases": ["rainy_villa_hall"],
                "tags": ["mansion", "night", "surveillance"],
            }
        ]
    }
    (tmp_path / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

    resolved = resolve_asset_path("background", "rainy_villa_hall.png", tmp_path, "听涛阁书房")

    assert resolved == asset_path.resolve()


def test_resolve_asset_path_uses_background_library_with_chinese_hints(tmp_path: Path) -> None:
    background_dir = tmp_path / "backgrounds"
    background_dir.mkdir(parents=True)
    overview_path = background_dir / "总.jpg"
    front_path = background_dir / "前厅.png"
    overview_path.write_bytes(b"png")
    front_path.write_bytes(b"png")
    (background_dir / "library.json").write_text(
        json.dumps(
            [
                {
                    "id": "总",
                    "path": "backgrounds/总.jpg",
                    "aliases": ["default", "大厅"],
                    "tags": ["default", "室内", "大厅"],
                },
                {
                    "id": "前厅",
                    "path": "backgrounds/前厅.png",
                    "aliases": ["front hall", "案发前厅"],
                    "tags": ["室内", "前厅", "门厅"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    resolved = resolve_asset_path("background", "bg.png", tmp_path, "案发前厅", "听涛阁前厅")

    assert resolved == front_path.resolve()


def test_resolve_asset_path_falls_back_to_default_background_library_entry(tmp_path: Path) -> None:
    background_dir = tmp_path / "backgrounds"
    background_dir.mkdir(parents=True)
    default_path = background_dir / "总.jpg"
    alt_path = background_dir / "前厅.png"
    default_path.write_bytes(b"png")
    alt_path.write_bytes(b"png")
    (background_dir / "library.json").write_text(
        json.dumps(
            [
                {
                    "id": "总",
                    "path": "backgrounds/总.jpg",
                    "aliases": ["default"],
                    "tags": ["default", "大厅"],
                },
                {
                    "id": "前厅",
                    "path": "backgrounds/前厅.png",
                    "aliases": ["展厅"],
                    "tags": ["室内", "展厅"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    resolved = resolve_asset_path("background", "totally_unknown_bg.png", tmp_path)

    assert resolved == default_path.resolve()


def test_resolve_asset_path_returns_normalized_target_when_catalog_misses(tmp_path: Path) -> None:
    resolved = resolve_asset_path("interactable", "Unknown Tool.PNG", tmp_path)

    assert resolved == (tmp_path / "interactables" / "unknown_tool.png").resolve()


def test_repo_asset_library_resolves_png_hint_to_curated_webp_background() -> None:
    resolved = resolve_asset_path(
        "background",
        "mansion_foyer_night.png",
        DEFAULT_ASSET_LIBRARY_ROOT,
    )

    assert resolved == (
        DEFAULT_ASSET_LIBRARY_ROOT / "backgrounds" / "mansion_foyer_night.webp"
    ).resolve()


def test_repo_asset_library_resolves_curated_cybernoir_background_from_chinese_hint() -> None:
    resolved = resolve_asset_path(
        "background",
        "bg.png",
        DEFAULT_ASSET_LIBRARY_ROOT,
        "赛博控制间",
    )

    assert resolved == (
        DEFAULT_ASSET_LIBRARY_ROOT / "backgrounds" / "cybernoir_control_desk.png"
    ).resolve()


def test_repo_asset_catalog_resolves_new_detective_prop_alias() -> None:
    resolved = resolve_asset_path(
        "interactable",
        "evidence_item.png",
        DEFAULT_ASSET_LIBRARY_ROOT,
        "黄铜钥匙",
    )

    assert resolved == (
        DEFAULT_ASSET_LIBRARY_ROOT / "interactables" / "brass_key.png"
    ).resolve()
