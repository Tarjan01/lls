"""Story JSON loading and validation for selectable demo cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from reverse_detective.models import (
    GameBackgroundDefinition,
    StoryDefinition,
    StoryPremise,
    StoryRanking,
    StoryRole,
    StoryRule,
    StoryTool,
)


DEFAULT_STORIES_DIR = Path("stories")
BACKGROUND_FILE_NAME = "game_background.json"
STORY_CONFIG_FILE_NAME = "story.json"
STORY_CACHE_FILE_NAME = "cached_initial_scene.json"


class StoryValidationError(ValueError):
    """Raised when a story JSON file does not match the expected schema."""


def load_story_catalog(stories_dir: Path | None = None) -> tuple[StoryDefinition, ...]:
    """Load all JSON story definitions from the stories directory."""

    root = stories_dir or DEFAULT_STORIES_DIR
    if not root.exists():
        raise StoryValidationError(f"Stories directory does not exist: {root}")

    background = load_game_background(root / BACKGROUND_FILE_NAME)
    story_files = sorted(
        child / STORY_CONFIG_FILE_NAME
        for child in root.iterdir()
        if child.is_dir() and (child / STORY_CONFIG_FILE_NAME).is_file()
    )
    if not story_files:
        raise StoryValidationError(f"No story JSON files found in: {root}")

    stories = tuple(load_story_definition(path, background) for path in story_files)
    if len({story.id for story in stories}) != len(stories):
        raise StoryValidationError("Story ids must be unique across the story catalog.")
    return stories


def load_game_background(path: Path | None = None) -> GameBackgroundDefinition:
    """Load the global game background used by all dossiers."""

    background_path = path or (DEFAULT_STORIES_DIR / BACKGROUND_FILE_NAME)
    try:
        raw_payload = json.loads(background_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StoryValidationError(f"Game background file was not found: {background_path}") from exc
    except json.JSONDecodeError as exc:
        raise StoryValidationError(f"Invalid JSON in {background_path}: {exc.msg}") from exc

    payload = _require_mapping(raw_payload, str(background_path))
    _require_exact_keys(
        payload,
        {"game_title", "game_subtitle", "operator_name", "background", "briefing", "menu_intro"},
        str(background_path),
    )

    return GameBackgroundDefinition(
        game_title=_require_non_empty_string(payload["game_title"], f"{background_path}.game_title"),
        game_subtitle=_require_non_empty_string(
            payload["game_subtitle"], f"{background_path}.game_subtitle"
        ),
        operator_name=_require_non_empty_string(
            payload["operator_name"], f"{background_path}.operator_name"
        ),
        background=_require_non_empty_string(payload["background"], f"{background_path}.background"),
        briefing=_require_non_empty_string(payload["briefing"], f"{background_path}.briefing"),
        menu_intro=_require_non_empty_string(payload["menu_intro"], f"{background_path}.menu_intro"),
    )


def load_story_definition(
    path: Path,
    background: GameBackgroundDefinition | None = None,
) -> StoryDefinition:
    """Load and validate one story JSON file."""

    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StoryValidationError(f"Story file was not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise StoryValidationError(f"Invalid JSON in {path}: {exc.msg}") from exc

    payload = _require_mapping(raw_payload, str(path))
    _require_exact_keys(
        payload,
        {"id", "title", "subtitle", "case", "roles", "scoring", "rankings"},
        str(path),
    )
    story_root = path.parent.parent if path.name == STORY_CONFIG_FILE_NAME else path.parent
    game_background = background or load_game_background(story_root / BACKGROUND_FILE_NAME)

    case_data = _require_mapping(payload["case"], f"{path}.case")
    _require_exact_keys(
        case_data,
        {
            "location",
            "setting",
            "core_case",
            "opening_hook",
            "victim",
            "pursuer",
        },
        f"{path}.case",
    )
    victim_data = _require_mapping(case_data["victim"], f"{path}.case.victim")
    _require_exact_keys(victim_data, {"name", "identity"}, f"{path}.case.victim")
    pursuer_data = _require_mapping(case_data["pursuer"], f"{path}.case.pursuer")
    _require_exact_keys(pursuer_data, {"name", "identity"}, f"{path}.case.pursuer")

    roles_raw = _require_sequence(payload["roles"], f"{path}.roles")
    if not roles_raw:
        raise StoryValidationError(f"{path}.roles must contain at least one role.")
    roles = tuple(_parse_role(item, index, path) for index, item in enumerate(roles_raw))

    scoring_data = _require_mapping(payload["scoring"], f"{path}.scoring")
    _require_exact_keys(
        scoring_data,
        {"base_score", "evidence_penalties", "task_bonuses"},
        f"{path}.scoring",
    )
    penalties = tuple(
        _parse_rule(item, index, f"{path}.scoring.evidence_penalties")
        for index, item in enumerate(
            _require_sequence(scoring_data["evidence_penalties"], f"{path}.scoring.evidence_penalties")
        )
    )
    bonuses = tuple(
        _parse_rule(item, index, f"{path}.scoring.task_bonuses")
        for index, item in enumerate(
            _require_sequence(scoring_data["task_bonuses"], f"{path}.scoring.task_bonuses")
        )
    )
    rankings = tuple(
        _parse_ranking(item, index, f"{path}.rankings")
        for index, item in enumerate(_require_sequence(payload["rankings"], f"{path}.rankings"))
    )

    return StoryDefinition(
        id=_require_non_empty_string(payload["id"], f"{path}.id"),
        title=_require_non_empty_string(payload["title"], f"{path}.title"),
        subtitle=_require_non_empty_string(payload["subtitle"], f"{path}.subtitle"),
        simulation_operator_name=game_background.operator_name,
        simulation_background=game_background.background,
        simulation_briefing=game_background.briefing,
        location=_require_non_empty_string(case_data["location"], f"{path}.case.location"),
        setting=_require_non_empty_string(case_data["setting"], f"{path}.case.setting"),
        core_case=_require_non_empty_string(case_data["core_case"], f"{path}.case.core_case"),
        opening_hook=_require_non_empty_string(
            case_data["opening_hook"], f"{path}.case.opening_hook"
        ),
        victim_name=_require_non_empty_string(victim_data["name"], f"{path}.case.victim.name"),
        victim_identity=_require_non_empty_string(
            victim_data["identity"], f"{path}.case.victim.identity"
        ),
        detective_name=_require_non_empty_string(
            pursuer_data["name"], f"{path}.case.pursuer.name"
        ),
        detective_identity=_require_non_empty_string(
            pursuer_data["identity"], f"{path}.case.pursuer.identity"
        ),
        roles=roles,
        base_score=_require_int(scoring_data["base_score"], f"{path}.scoring.base_score"),
        evidence_penalties=penalties,
        task_bonuses=bonuses,
        rankings=rankings,
    )


def build_story_premise(story: StoryDefinition, role_id: str | None = None) -> StoryPremise:
    """Build the concrete AI premise from a story definition and selected role."""

    role = story.roles[0] if role_id is None else _find_role(story, role_id)
    player_identity = (
        f"你是{role.display_name}，潜入《逆转侦探》的案件模拟，准备重演{story.victim_name}之死。"
        f"{role.background}"
    )
    initial_goal = (
        f"在{story.location}的这一夜，以{role.display_name}的身份让{story.victim_name}"
        "死于看似意外或难以直接归责的事故，同时尽量保留退路并完成隐藏目标。"
    )
    return StoryPremise(
        story_id=story.id,
        story_title=story.title,
        story_subtitle=story.subtitle,
        simulation_operator_name=story.simulation_operator_name,
        simulation_background=story.simulation_background,
        simulation_briefing=story.simulation_briefing,
        player_role_id=role.id,
        player_role_name=role.display_name,
        player_display_name=role.name,
        player_identity=player_identity,
        player_strategy_kind=role.strategy_kind,
        victim_identity=story.victim_identity,
        victim_name=story.victim_name,
        detective_identity=story.detective_identity,
        detective_name=story.detective_name,
        setting=story.setting,
        motive=role.motive,
        initial_goal=initial_goal,
        hidden_objective=role.hidden_objective,
        opening_hook=story.opening_hook,
        primary_tool_name=role.primary_tool_name,
        secondary_tool_name=role.secondary_tool_name,
    )


def _find_role(story: StoryDefinition, role_id: str) -> StoryRole:
    for role in story.roles:
        if role.id == role_id:
            return role
    raise StoryValidationError(f"Role {role_id!r} was not found in story {story.id!r}.")


def _parse_role(value: Any, index: int, path: Path) -> StoryRole:
    role_path = f"{path}.roles[{index}]"
    role_data = _require_mapping(value, role_path)
    _require_exact_keys(
        role_data,
        {
            "id",
            "title",
            "name",
            "background",
            "motive",
            "special_conditions",
            "signature_tools",
            "hidden_objective",
            "strategy_kind",
        },
        role_path,
    )
    tools = tuple(
        _parse_tool(item, tool_index, f"{role_path}.signature_tools")
        for tool_index, item in enumerate(
            _require_sequence(role_data["signature_tools"], f"{role_path}.signature_tools")
        )
    )
    if not tools:
        raise StoryValidationError(f"{role_path}.signature_tools must not be empty.")

    return StoryRole(
        id=_require_non_empty_string(role_data["id"], f"{role_path}.id"),
        title=_require_non_empty_string(role_data["title"], f"{role_path}.title"),
        name=_require_non_empty_string(role_data["name"], f"{role_path}.name"),
        background=_require_non_empty_string(role_data["background"], f"{role_path}.background"),
        motive=_require_non_empty_string(role_data["motive"], f"{role_path}.motive"),
        special_conditions=tuple(
            _require_non_empty_string(item, f"{role_path}.special_conditions[{condition_index}]")
            for condition_index, item in enumerate(
                _require_sequence(role_data["special_conditions"], f"{role_path}.special_conditions")
            )
        ),
        signature_tools=tools,
        hidden_objective=_require_non_empty_string(
            role_data["hidden_objective"], f"{role_path}.hidden_objective"
        ),
        strategy_kind=_require_non_empty_string(
            role_data["strategy_kind"], f"{role_path}.strategy_kind"
        ),
    )


def _parse_tool(value: Any, index: int, path: str) -> StoryTool:
    tool_path = f"{path}[{index}]"
    tool_data = _require_mapping(value, tool_path)
    _require_exact_keys(tool_data, {"name", "description"}, tool_path)
    return StoryTool(
        name=_require_non_empty_string(tool_data["name"], f"{tool_path}.name"),
        description=_require_non_empty_string(tool_data["description"], f"{tool_path}.description"),
    )


def _parse_rule(value: Any, index: int, path: str) -> StoryRule:
    rule_path = f"{path}[{index}]"
    rule_data = _require_mapping(value, rule_path)
    _require_exact_keys(rule_data, {"title", "description", "score_delta"}, rule_path)
    return StoryRule(
        title=_require_non_empty_string(rule_data["title"], f"{rule_path}.title"),
        description=_require_non_empty_string(rule_data["description"], f"{rule_path}.description"),
        score_delta=_require_int(rule_data["score_delta"], f"{rule_path}.score_delta"),
    )


def _parse_ranking(value: Any, index: int, path: str) -> StoryRanking:
    rank_path = f"{path}[{index}]"
    rank_data = _require_mapping(value, rank_path)
    _require_exact_keys(rank_data, {"rank", "score_range", "description"}, rank_path)
    return StoryRanking(
        rank=_require_non_empty_string(rank_data["rank"], f"{rank_path}.rank"),
        score_range=_require_non_empty_string(rank_data["score_range"], f"{rank_path}.score_range"),
        description=_require_non_empty_string(rank_data["description"], f"{rank_path}.description"),
    )


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StoryValidationError(f"{path} must be an object.")
    return dict(value)


def _require_sequence(value: Any, path: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise StoryValidationError(f"{path} must be an array.")
    return list(value)


def _require_non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StoryValidationError(f"{path} must be a non-empty string.")
    return value.strip()


def _require_int(value: Any, path: str) -> int:
    if not isinstance(value, int):
        raise StoryValidationError(f"{path} must be an integer.")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], path: str) -> None:
    actual = set(value.keys())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        fragments: list[str] = []
        if missing:
            fragments.append(f"missing keys {missing!r}")
        if extra:
            fragments.append(f"unexpected keys {extra!r}")
        raise StoryValidationError(f"{path} has invalid schema: {', '.join(fragments)}.")
