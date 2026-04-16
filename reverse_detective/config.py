"""Configuration loading for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
import json
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


def load_api_key(credentials_path: Path, provider: str) -> str:
    """Load an API key from the configured credentials file."""

    if not credentials_path.exists():
        return ""

    try:
        credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""

    if not isinstance(credentials, dict):
        return ""

    candidate_keys = [
        "api_key",
        "crs_api_key",
        provider,
        f"{provider}_api_key",
    ]
    for key in candidate_keys:
        value = credentials.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def save_config(config: AppConfig, config_path: Path | None = None) -> None:
    """Persist app configuration back to config.toml."""

    path = config_path or DEFAULT_CONFIG_PATH
    content = "\n".join(
        [
            "[display]",
            f"title = {_toml_quote(config.display.title)}",
            f"width = {config.display.width}",
            f"height = {config.display.height}",
            f"fps = {config.display.fps}",
            "",
            "[ai]",
            f"provider = {_toml_quote(config.ai.provider)}",
            f"base_url = {_toml_quote(config.ai.base_url)}",
            f"model = {_toml_quote(config.ai.model)}",
            f"timeout_seconds = {config.ai.timeout_seconds}",
            f"use_mock_when_unconfigured = {_toml_bool(config.ai.use_mock_when_unconfigured)}",
            f"fallback_to_mock_on_error = {_toml_bool(config.ai.fallback_to_mock_on_error)}",
            f"credentials_path = {_toml_quote(str(config.ai.credentials_path))}",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def save_api_key(credentials_path: Path, provider: str, api_key: str) -> None:
    """Persist the API key to the configured credentials file."""

    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if credentials_path.exists():
        try:
            raw = json.loads(credentials_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            existing = raw

    cleaned = api_key.strip()
    if cleaned:
        existing["api_key"] = cleaned
        existing["crs_api_key"] = cleaned
        existing[provider] = cleaned
        existing[f"{provider}_api_key"] = cleaned
    else:
        for key in ("api_key", "crs_api_key", provider, f"{provider}_api_key"):
            existing.pop(key, None)

    credentials_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
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


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"
