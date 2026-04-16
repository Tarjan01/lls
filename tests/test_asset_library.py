from __future__ import annotations

import json
from pathlib import Path

from reverse_detective.utils.assets import resolve_asset_path


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


def test_resolve_asset_path_returns_normalized_target_when_catalog_misses(tmp_path: Path) -> None:
    resolved = resolve_asset_path("interactable", "Unknown Tool.PNG", tmp_path)

    assert resolved == (tmp_path / "interactables" / "unknown_tool.png").resolve()
