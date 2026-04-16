"""Compatibility entrypoint for the Reverse Detective demo."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType


PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_DEPENDENCIES = frozenset({"pygame", "openai"})

__all__ = ["main", "run_game"]


def run_game() -> None:
    """Run the game application in the current interpreter."""

    app_module = _load_app_module(wrap_runtime_dependency_error=True)
    app_module.run_game()


def main() -> None:
    """CLI script entrypoint with uv bootstrap fallback."""

    try:
        app_module = _load_app_module(wrap_runtime_dependency_error=False)
    except ModuleNotFoundError as exc:
        if not _should_bootstrap_with_uv(exc):
            raise
        raise SystemExit(_run_with_uv(exc.name or "pygame")) from exc

    app_module.main()


def _load_app_module(*, wrap_runtime_dependency_error: bool) -> ModuleType:
    try:
        return import_module("reverse_detective.app")
    except ModuleNotFoundError as exc:
        if not _should_bootstrap_with_uv(exc):
            raise
        if not wrap_runtime_dependency_error:
            raise
        raise RuntimeError(_build_missing_dependency_message(exc.name or "pygame")) from exc


def _should_bootstrap_with_uv(exc: ModuleNotFoundError) -> bool:
    return (exc.name or "") in RUNTIME_DEPENDENCIES


def _run_with_uv(package_name: str) -> int:
    uv_path = shutil.which("uv")
    if uv_path is None:
        print(_build_missing_dependency_message(package_name), file=sys.stderr)
        return 1

    print(
        (
            f"Detected missing runtime dependency '{package_name}' in the current interpreter. "
            "Starting the project with `uv run game`."
        ),
        file=sys.stderr,
    )
    completed = subprocess.run([uv_path, "run", "game"], cwd=PROJECT_ROOT, check=False)
    return completed.returncode


def _build_missing_dependency_message(package_name: str) -> str:
    return (
        f"Current interpreter is missing the runtime dependency '{package_name}'. "
        "Run `uv sync --dev`, then start the demo with `uv run game`."
    )


if __name__ == "__main__":
    main()
