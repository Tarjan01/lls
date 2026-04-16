"""Configuration loading for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib


DEFAULT_CONFIG_PATH = Path("config.toml")
DEFAULT_CREDENTIALS_PATH = Path("~/.reverse_detective/credentials.json").expanduser()


@dataclass(frozen=True, slots=True)
class DisplayConfig:
    title: str
    width: int
    height: int
    fps: int


@dataclass(frozen=True, slots=True)
class AIConfig:
    provider: str
    base_url: str
    model: str
    timeout_seconds: float
    use_mock_when_unconfigured: bool
    fallback_to_mock_on_error: bool
    credentials_path: Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    display: DisplayConfig
    ai: AIConfig


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load application configuration from TOML with sane defaults."""

    config_data = _read_toml(config_path or DEFAULT_CONFIG_PATH)
    display_data = _as_dict(config_data.get("display"))
    ai_data = _as_dict(config_data.get("ai"))

    return AppConfig(
        display=DisplayConfig(
            title=str(display_data.get("title", "Reverse Detective Demo")),
            width=int(display_data.get("width", 1280)),
            height=int(display_data.get("height", 720)),
            fps=int(display_data.get("fps", 60)),
        ),
        ai=AIConfig(
            provider=str(ai_data.get("provider", "crs")),
            base_url=str(ai_data.get("base_url", "")).strip(),
            model=str(ai_data.get("model", "gpt-4.1-mini")),
            timeout_seconds=float(ai_data.get("timeout_seconds", 30)),
            use_mock_when_unconfigured=bool(ai_data.get("use_mock_when_unconfigured", True)),
            fallback_to_mock_on_error=bool(ai_data.get("fallback_to_mock_on_error", True)),
            credentials_path=Path(
                str(ai_data.get("credentials_path", DEFAULT_CREDENTIALS_PATH))
            ).expanduser(),
        ),
    )


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open("rb") as file:
        data = tomllib.load(file)

    return _as_dict(data)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}
