from __future__ import annotations

import main as root_entry
import pytest


def test_run_game_raises_helpful_error_for_missing_runtime_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _missing_module_error("pygame")

    def fake_import(_: str):
        raise error

    monkeypatch.setattr(root_entry, "import_module", fake_import)

    with pytest.raises(RuntimeError, match="uv run game"):
        root_entry.run_game()


def test_main_bootstraps_with_uv_for_missing_runtime_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _missing_module_error("pygame")

    def fake_import(_: str):
        raise error

    monkeypatch.setattr(root_entry, "import_module", fake_import)
    monkeypatch.setattr(root_entry, "_run_with_uv", lambda package_name: 0)

    with pytest.raises(SystemExit) as exit_info:
        root_entry.main()

    assert exit_info.value.code == 0


def test_main_reraises_non_runtime_import_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    error = _missing_module_error("tomllib")

    def fake_import(_: str):
        raise error

    monkeypatch.setattr(root_entry, "import_module", fake_import)

    with pytest.raises(ModuleNotFoundError):
        root_entry.main()


def _missing_module_error(name: str) -> ModuleNotFoundError:
    error = ModuleNotFoundError(f"No module named '{name}'")
    error.name = name
    return error
