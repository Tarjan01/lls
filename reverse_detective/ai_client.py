"""AI scene generation entrypoint for the Reverse Detective demo."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from reverse_detective.config import AIConfig
from reverse_detective.game_state import PendingChoice
from reverse_detective.models import ActionRecord, SceneState, StoryPremise
from reverse_detective.scene_loader import load_scene_payload, scene_to_dict
from reverse_detective.story_loader import build_story_premise, load_story_catalog


PROMPT_SCHEMA = {
    "scene": {
        "background_image": "string",
        "bgm": "string",
        "description": "string",
    },
    "npcs": [
        {
            "id": "string",
            "name": "string",
            "image": "string",
            "position": [0, 0],
            "patrol": [[0, 0], [10, 10]],
        }
    ],
    "interactables": [
        {
            "id": "string",
            "name": "string",
            "image": "string",
            "position": [0, 0],
            "options": [{"label": "string", "action_id": "string"}],
        }
    ],
    "narrative": "string",
    "game_status": "ongoing",
    "ending_text": None,
}


@dataclass(frozen=True, slots=True)
class AIRequestPayload:
    premise: StoryPremise
    current_scene: SceneState | None
    history: tuple[ActionRecord, ...]
    latest_choice: PendingChoice | None


class AIClientError(RuntimeError):
    """Raised when the configured AI provider cannot generate a valid scene."""


class ReverseDetectiveAIClient:
    """Facade for live OpenAI-compatible requests with a local mock fallback."""

    def __init__(self, config: AIConfig):
        self._config = config
        self._mock_engine = _MockStoryEngine()
        self._api_key = self._load_api_key(config.credentials_path)
        self._live_enabled = bool(config.base_url and config.model and self._api_key)
        self._last_mode_label = "Live API" if self._live_enabled else "Mock Story"

        if not self._live_enabled and not config.use_mock_when_unconfigured:
            raise AIClientError(
                "AI provider is not fully configured and mock mode has been disabled."
            )

    @property
    def mode_label(self) -> str:
        return self._last_mode_label

    def generate_initial_scene(self, premise: StoryPremise) -> SceneState:
        request = AIRequestPayload(
            premise=premise,
            current_scene=None,
            history=(),
            latest_choice=None,
        )
        return self._generate_scene(request)

    def generate_next_scene(
        self,
        premise: StoryPremise,
        current_scene: SceneState,
        history: list[ActionRecord],
        latest_choice: PendingChoice,
    ) -> SceneState:
        request = AIRequestPayload(
            premise=premise,
            current_scene=current_scene,
            history=tuple(history),
            latest_choice=latest_choice,
        )
        return self._generate_scene(request)

    def _generate_scene(self, request: AIRequestPayload) -> SceneState:
        if self._live_enabled:
            try:
                scene = self._generate_live_scene(request)
                self._last_mode_label = "Live API"
                return scene
            except Exception as exc:
                if not self._config.fallback_to_mock_on_error:
                    raise AIClientError(f"Live AI request failed: {exc}") from exc

        self._last_mode_label = "Mock Story"
        return self._mock_engine.generate_scene(request)

    def _generate_live_scene(self, request: AIRequestPayload) -> SceneState:
        from openai import OpenAI

        client = OpenAI(
            api_key=self._api_key,
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
        )

        with client.responses.stream(
            model=self._config.model,
            input=self._build_response_input(request),
            reasoning={"effort": self._config.reasoning_effort},
            text={"format": {"type": "json_object"}},
            store=not self._config.disable_response_storage,
            temperature=0.8,
        ) as stream:
            response, streamed_text = self._consume_response_stream(stream)

        raw_content = self._extract_response_content(response, streamed_text)
        try:
            return load_scene_payload(raw_content)
        except Exception as exc:
            raise AIClientError(f"Live AI returned invalid scene JSON: {exc}") from exc

    def _build_system_prompt(self) -> str:
        schema_text = json.dumps(PROMPT_SCHEMA, ensure_ascii=False, indent=2)
        return (
            "你是一个反转型侦探游戏的场景状态生成器。"
            "你必须只输出一个 JSON 对象，不得输出任何额外文本、解释、前缀、后缀或 Markdown 代码块。"
            "每次玩家做出选择后，你都要基于【初始设定 + 完整历史操作记录 + 本次选择】生成新的场景 JSON。"
            "JSON 必须严格遵循以下 schema，字段不得缺失，不得新增字段：\n"
            f"{schema_text}\n"
            "要求："
            "1. game_status 只能是 ongoing、player_win、player_lose、special_ending。"
            "2. ending_text 只有在非 ongoing 结局时才填写具体结局文本，否则必须为 null。"
            "3. npcs 中每个 patrol 要么是 null，要么是二维整型坐标数组。"
            "4. narrative 需要描述当前局面和风险。"
            "5. 所有文本使用简体中文。"
        )

    def _build_user_prompt(self, request: AIRequestPayload) -> str:
        payload = {
            "request_type": "advance_scene" if request.latest_choice else "initial_scene",
            "premise": _premise_to_dict(request.premise),
            "history": [_history_record_to_dict(item) for item in request.history],
            "latest_choice": None
            if request.latest_choice is None
            else _pending_choice_to_dict(request.latest_choice),
            "current_scene": None
            if request.current_scene is None
            else scene_to_dict(request.current_scene),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _build_response_input(self, request: AIRequestPayload) -> list[dict[str, Any]]:
        return [
            {
                "type": "message",
                "role": "developer",
                "content": self._build_system_prompt(),
            },
            {
                "type": "message",
                "role": "user",
                "content": self._build_user_prompt(request),
            },
        ]

    def _consume_response_stream(self, stream: Any) -> tuple[Any, str]:
        chunks: list[str] = []
        for event in stream:
            if getattr(event, "type", None) != "response.output_text.delta":
                continue
            delta = getattr(event, "delta", None)
            if isinstance(delta, str) and delta:
                chunks.append(delta)

        return stream.get_final_response(), "".join(chunks)

    def _extract_response_content(self, response: Any, streamed_text: str = "") -> str:
        if streamed_text.strip():
            return streamed_text

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        output_items = getattr(response, "output", None)
        if isinstance(output_items, list):
            parts: list[str] = []
            for item in output_items:
                content = getattr(item, "content", None)
                if not isinstance(content, list):
                    continue
                for content_item in content:
                    text = getattr(content_item, "text", None)
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
                    elif isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                        parts.append(content_item["text"])
            if parts:
                return "".join(parts)

        raise AIClientError("Live AI response did not contain textual JSON output.")

    def _build_system_prompt(self) -> str:
        schema_text = json.dumps(PROMPT_SCHEMA, ensure_ascii=False, indent=2)
        return (
            "You generate scene JSON for a reverse-detective game. "
            "Return exactly one JSON object and nothing else. "
            "Do not return markdown, explanations, or code fences. "
            "After each player choice, generate the next scene from the initial premise, full action history, and latest choice. "
            "The JSON must match this schema exactly with no missing or extra fields:\n"
            f"{schema_text}\n"
            "Requirements:\n"
            "1. game_status must be one of ongoing, player_win, player_lose, special_ending.\n"
            "2. ending_text must be null when game_status is ongoing, otherwise it must contain a concrete ending text.\n"
            "3. Every position must be a JSON array [x, y] of integers.\n"
            "4. Every patrol must be null or an array of at least two coordinate arrays like [[x, y], [x, y]]. Never use coordinate objects.\n"
            "5. narrative must describe the current situation and risk.\n"
            "6. All visible text content must be Simplified Chinese.\n"
        )

    def _load_api_key(self, credentials_path: Path) -> str | None:
        if not credentials_path.exists():
            return None

        try:
            with credentials_path.open("r", encoding="utf-8") as file:
                credentials = json.load(file)
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(credentials, dict):
            return None

        candidate_keys = [
            "api_key",
            "crs_api_key",
            self._config.provider,
            f"{self._config.provider}_api_key",
        ]
        for key in candidate_keys:
            value = credentials.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return None


def _legacy_build_default_premise() -> StoryPremise:
    """Return the default demo premise used by both mock and live modes."""

    return StoryPremise(
        story_id="legacy_demo_case",
        story_title="山庄遗产说明会",
        story_subtitle="旧版本地 mock 剧本",
        simulation_operator_name="江川",
        simulation_background="江川通过扮演凶手来倒推现实案件的破局点。",
        simulation_briefing="玩家以嫌疑人身份进入案件发生前的最后时段，尝试重演凶案。",
        player_role_id="legacy_secretary",
        player_role_name="私人秘书林岚",
        player_display_name="林岚",
        player_identity="你是赵公馆的私人秘书林岚，擅长维持体面，也擅长隐藏自己的真实意图。",
        player_strategy_kind="social",
        victim_identity="赵公馆主人赵铭刚发现你挪用了公馆修缮基金，准备在今晚的遗产说明会上公开账本。",
        victim_name="赵铭",
        detective_identity="侦探顾闻舟以顾问身份受邀到场，正在观察每个人的情绪和站位。",
        detective_name="顾闻舟",
        setting="暴雨压住了整座山庄的声音，会客厅与书房相连，老旧配电箱时不时发出轻响。",
        motive="如果赵铭在今晚开口，你多年来经营的一切都会崩塌。",
        initial_goal="在不暴露身份的前提下，让赵铭死于一场看似意外或无法指向你的事件。",
        hidden_objective="在案发后及时销毁挪用账目。",
        opening_hook="遗产说明会开始前，所有人的注意力都被暴雨和账本牵住。",
        primary_tool_name="毒酒",
        secondary_tool_name="配电箱",
    )


class _LegacyMockStoryEngine:
    """Deterministic local story engine used when no live AI is available."""

    def generate_scene(self, request: AIRequestPayload) -> SceneState:
        history = list(request.history)
        if request.latest_choice is not None:
            history.append(request.latest_choice.to_record())

        flags = self._derive_flags(history)

        if request.latest_choice is None:
            payload = self._build_ongoing_scene(
                request.premise,
                flags,
                "雨声掩住了会客厅里的低语。赵铭站在落地窗前，顾闻舟在一旁缓慢踱步，你知道自己只剩一次机会。",
            )
        else:
            payload = self._build_from_latest_choice(request.premise, flags, request.latest_choice)

        return load_scene_payload(payload)

    def _build_from_latest_choice(
        self,
        premise: StoryPremise,
        flags: dict[str, bool],
        latest_choice: PendingChoice,
    ) -> dict[str, Any]:
        action_id = latest_choice.action_id

        if action_id == "darkness_strike":
            if flags["gloves_on"]:
                return self._build_terminal_scene(
                    game_status="player_win",
                    background_image="scene_villa_blackout.png",
                    description="停电后的大厅只剩应急灯与窗外闪电轮流照亮血迹。",
                    narrative="你借黑暗与惊雷的掩护从背后刺向赵铭，随后把自己混进慌乱的人群里。",
                    ending_text="顾闻舟最终只能得到一桩混乱中的凶案。没有指向你的指纹，也没有能还原黑暗中站位的目击证词。你赢了。",
                )
            return self._build_terminal_scene(
                game_status="player_lose",
                background_image="scene_villa_blackout.png",
                description="闪电划过时，顾闻舟看见你来不及藏起的手与刀。",
                narrative="你确实动手成功了，但指纹和血迹路线在应急灯下暴露无遗。",
                ending_text="顾闻舟当场锁定了你。停电没有帮你隐身，反而让你成为唯一合理的嫌疑人。你失败了。",
            )

        if action_id == "wait_for_poison":
            return self._build_terminal_scene(
                game_status="special_ending",
                background_image="scene_villa_blackout.png"
                if flags["power_cut"]
                else "scene_villa_hall.png",
                description="赵铭手中的酒杯碎裂在地，猩红酒液沿着地毯边缘蔓延。",
                narrative="药效在最糟糕的时机发作。赵铭踉跄着撞碎展柜，所有人都先注意到倒塌的玻璃，而不是你收回去的手。",
                ending_text="官方结论是一场意外。顾闻舟觉得哪里不对，却找不到能把你送上审判席的那条证据链。你得到了一场特殊结局。",
            )

        if action_id == "darkness_approach":
            return self._build_terminal_scene(
                game_status="player_lose",
                background_image="scene_villa_blackout.png",
                description="黑暗中有手电筒骤然亮起，把你和赵铭之间的距离照得无所遁形。",
                narrative="你试图趁黑靠近赵铭，却被顾闻舟的手电光直接钉在原地。",
                ending_text="没有武器、没有退路、没有借口。赵铭当场喊破你的名字，顾闻舟也不再需要更多试探。你失败了。",
            )

        if action_id == "approach_victim" and flags["knife_taken"] and not flags["power_cut"]:
            return self._build_terminal_scene(
                game_status="player_lose",
                background_image="scene_villa_hall.png",
                description="暖黄灯光下，口袋边缘短暂露出的金属反光并不宽容。",
                narrative="你靠近赵铭时，顾闻舟先看见了你藏不稳的折刀。",
                ending_text="赵铭没有死，但你已经失去了继续伪装的空间。顾闻舟把人群和证据都锁定到你身上。你失败了。",
            )

        if action_id == "inspect_ledger":
            return self._build_ongoing_scene(
                premise,
                flags,
                "账本里清楚记着那笔被你挪走的修缮基金，甚至还有赵铭准备在今晚公开的批注。时间窗口比你想象得更窄。",
            )

        if action_id == "poison_wine":
            return self._build_ongoing_scene(
                premise,
                flags,
                "你把无色药剂滴进赵铭常喝的红酒里。顾闻舟正背对着你观察落地窗外的山路，没有人注意到这一瞬。",
            )

        if action_id == "cut_power":
            return self._build_ongoing_scene(
                premise,
                flags,
                "整座会客厅突然陷入昏暗，只剩窗外闪电和角落应急灯留下断续的轮廓。赵铭本能地朝窗边后退，顾闻舟也停下了原本的巡逻。",
            )

        if action_id == "wear_gloves":
            return self._build_ongoing_scene(
                premise,
                flags,
                "柔软的皮手套贴紧手指，你终于能在触碰任何东西时少留下一层真正属于自己的痕迹。",
            )

        if action_id == "take_knife":
            return self._build_ongoing_scene(
                premise,
                flags,
                "你把装饰架旁的折刀悄悄滑进袖口。它不大，但在一场黑暗和混乱里已经足够致命。",
            )

        return self._build_ongoing_scene(
            premise,
            flags,
            "你暂时按兵不动。赵铭还在和顾闻舟说话，但每一秒都在压缩你的余地。",
        )

    def _build_ongoing_scene(
        self,
        premise: StoryPremise,
        flags: dict[str, bool],
        narrative: str,
    ) -> dict[str, Any]:
        blackout = flags["power_cut"]
        victim_position = [940, 290] if blackout else [930, 250]
        detective_position = [360, 250] if blackout else [260, 250]
        detective_patrol = None if blackout else [[260, 250], [420, 250], [260, 250]]

        interactables: list[dict[str, Any]] = []
        if not flags["gloves_on"]:
            interactables.append(
                self._interactable(
                    "gloves",
                    "皮手套",
                    [180, 470],
                    [("戴上手套", "wear_gloves"), ("继续观察", "leave_gloves")],
                )
            )
        if not flags["knife_taken"]:
            interactables.append(
                self._interactable(
                    "knife",
                    "装饰折刀",
                    [380, 455],
                    [("把折刀藏进口袋", "take_knife"), ("先不要碰它", "leave_knife")],
                )
            )
        if not flags["wine_poisoned"]:
            interactables.append(
                self._interactable(
                    "wine",
                    "赵铭的红酒",
                    [740, 410],
                    [("往酒里下药", "poison_wine"), ("暂时不动酒杯", "leave_wine")],
                )
            )
        if not flags["power_cut"]:
            interactables.append(
                self._interactable(
                    "fuse_box",
                    "老旧配电箱",
                    [1030, 210],
                    [("切断电源", "cut_power"), ("维持照明", "keep_power")],
                )
            )

        interactables.append(
            self._interactable(
                "ledger",
                "遗产账本",
                [540, 435],
                [("翻看账本", "inspect_ledger"), ("合上账本", "ignore_ledger")],
            )
        )
        interactables.append(self._build_victim_interactable(flags))

        if flags["gloves_on"] and flags["knife_taken"] and blackout:
            scene_description = "停电后的会客厅被闪电切成一块块锐利的光影。"
        elif blackout:
            scene_description = "会客厅陷入半黑，只剩雨声、应急灯和玻璃上的反光。"
        else:
            scene_description = "会客厅铺着厚重地毯，暴雨把落地窗敲成了一面不断颤动的镜子。"

        return {
            "scene": {
                "background_image": "scene_villa_blackout.png" if blackout else "scene_villa_hall.png",
                "bgm": "storm_tension.mp3",
                "description": scene_description,
            },
            "npcs": [
                {
                    "id": "victim_zhao",
                    "name": "赵铭",
                    "image": "npc_zhao.png",
                    "position": victim_position,
                    "patrol": None,
                },
                {
                    "id": "detective_gu",
                    "name": "顾闻舟",
                    "image": "npc_gu.png",
                    "position": detective_position,
                    "patrol": detective_patrol,
                },
                {
                    "id": "housekeeper_qin",
                    "name": "管家秦姨",
                    "image": "npc_qin.png",
                    "position": [700, 235],
                    "patrol": None,
                },
            ],
            "interactables": interactables,
            "narrative": narrative,
            "game_status": "ongoing",
            "ending_text": None,
        }

    def _build_victim_interactable(self, flags: dict[str, bool]) -> dict[str, Any]:
        if flags["wine_poisoned"]:
            options = [("观察赵铭饮酒后的反应", "wait_for_poison"), ("暂时远离赵铭", "leave_victim")]
            name = "赵铭手边的阴影"
        elif flags["power_cut"] and flags["knife_taken"]:
            options = [("趁黑从背后动手", "darkness_strike"), ("再等一个空隙", "leave_victim")]
            name = "赵铭背后的暗影"
        elif flags["power_cut"]:
            options = [("趁黑逼近赵铭", "darkness_approach"), ("继续藏在角落", "leave_victim")]
            name = "摇晃的黑影"
        else:
            options = [("假意靠近赵铭套话", "approach_victim"), ("先保持距离", "leave_victim")]
            name = "赵铭身侧的空隙"

        return self._interactable("victim_window", name, [900, 360], options)

    def _build_terminal_scene(
        self,
        *,
        game_status: str,
        background_image: str,
        description: str,
        narrative: str,
        ending_text: str,
    ) -> dict[str, Any]:
        return {
            "scene": {
                "background_image": background_image,
                "bgm": "ending_resolve.mp3",
                "description": description,
            },
            "npcs": [
                {
                    "id": "victim_zhao",
                    "name": "赵铭",
                    "image": "npc_zhao.png",
                    "position": [930, 260],
                    "patrol": None,
                },
                {
                    "id": "detective_gu",
                    "name": "顾闻舟",
                    "image": "npc_gu.png",
                    "position": [420, 250],
                    "patrol": None,
                },
            ],
            "interactables": [],
            "narrative": narrative,
            "game_status": game_status,
            "ending_text": ending_text,
        }

    def _derive_flags(self, history: list[ActionRecord]) -> dict[str, bool]:
        action_ids = {record.action_id for record in history}
        return {
            "gloves_on": "wear_gloves" in action_ids,
            "knife_taken": "take_knife" in action_ids,
            "wine_poisoned": "poison_wine" in action_ids,
            "power_cut": "cut_power" in action_ids,
        }

    def _interactable(
        self,
        interactable_id: str,
        name: str,
        position: list[int],
        options: list[tuple[str, str]],
    ) -> dict[str, Any]:
        return {
            "id": interactable_id,
            "name": name,
            "image": f"{interactable_id}.png",
            "position": position,
            "options": [{"label": label, "action_id": action_id} for label, action_id in options],
        }


def _legacy_premise_to_dict(premise: StoryPremise) -> dict[str, str]:
    return {
        "player_identity": premise.player_identity,
        "victim_identity": premise.victim_identity,
        "detective_identity": premise.detective_identity,
        "setting": premise.setting,
        "motive": premise.motive,
        "initial_goal": premise.initial_goal,
    }


def _history_record_to_dict(record: ActionRecord) -> dict[str, Any]:
    return {
        "turn_index": record.turn_index,
        "interactable_id": record.interactable_id,
        "interactable_name": record.interactable_name,
        "label": record.label,
        "action_id": record.action_id,
    }


def _pending_choice_to_dict(choice: PendingChoice) -> dict[str, Any]:
    return {
        "turn_index": choice.turn_index,
        "interactable_id": choice.interactable_id,
        "interactable_name": choice.interactable_name,
        "label": choice.label,
        "action_id": choice.action_id,
    }


def build_default_premise() -> StoryPremise:
    """Return the default premise from the primary selectable story file."""

    stories = load_story_catalog()
    story = next(
        (candidate for candidate in stories if candidate.id == "tingtaoge_last_night"),
        stories[0],
    )
    return build_story_premise(story, story.roles[0].id)


class _MockStoryEngine:
    """Deterministic local story engine used when no live AI is available."""

    def generate_scene(self, request: AIRequestPayload) -> SceneState:
        history = list(request.history)
        if request.latest_choice is not None:
            history.append(request.latest_choice.to_record())

        flags = self._derive_flags(history)
        strategy = self._build_strategy_copy(request.premise)

        if request.latest_choice is None:
            payload = self._build_ongoing_scene(
                request.premise,
                flags,
                (
                    f"{request.premise.opening_hook}"
                    f" 你现在以{request.premise.player_role_name}的身份进入重演，只能沿着最危险的那条缝隙前进。"
                ),
                strategy,
            )
        else:
            payload = self._build_from_latest_choice(
                request.premise,
                flags,
                request.latest_choice,
                strategy,
            )

        return load_scene_payload(payload)

    def _build_from_latest_choice(
        self,
        premise: StoryPremise,
        flags: dict[str, bool],
        latest_choice: PendingChoice,
        strategy: dict[str, Any],
    ) -> dict[str, Any]:
        action_id = latest_choice.action_id

        if action_id == "execute_clean":
            return self._build_terminal_scene(
                premise=premise,
                game_status="player_win",
                background_image="scene_tingtaoge_blackout.png"
                if flags["support_ready"]
                else "scene_tingtaoge_study.png",
                description=strategy["clean_description"],
                narrative=strategy["clean_narrative"],
                ending_text=strategy["clean_ending"],
            )

        if action_id == "execute_risky":
            return self._build_terminal_scene(
                premise=premise,
                game_status=strategy["risky_status"],
                background_image="scene_tingtaoge_study.png",
                description=strategy["risky_description"],
                narrative=strategy["risky_narrative"],
                ending_text=strategy["risky_ending"],
            )

        if action_id == "rush_target":
            return self._build_terminal_scene(
                premise=premise,
                game_status="player_lose",
                background_image="scene_tingtaoge_study.png",
                description=strategy["rush_description"],
                narrative=strategy["rush_narrative"],
                ending_text=strategy["rush_ending"],
            )

        if action_id == "inspect_clue":
            return self._build_ongoing_scene(premise, flags, strategy["clue_narrative"], strategy)

        if action_id == "prepare_tool":
            return self._build_ongoing_scene(premise, flags, strategy["tool_narrative"], strategy)

        if action_id == "prepare_support":
            return self._build_ongoing_scene(
                premise,
                flags,
                strategy["support_narrative"],
                strategy,
            )

        return self._build_ongoing_scene(premise, flags, strategy["wait_narrative"], strategy)

    def _build_ongoing_scene(
        self,
        premise: StoryPremise,
        flags: dict[str, bool],
        narrative: str,
        strategy: dict[str, Any],
    ) -> dict[str, Any]:
        support_ready = flags["support_ready"]
        pursuer_position = [332, 242] if support_ready else [260, 250]
        pursuer_patrol = None if support_ready else [[260, 250], [420, 250], [260, 250]]
        victim_position = [924, 252] if not support_ready else [952, 282]

        interactables: list[dict[str, Any]] = []
        if not flags["clue_checked"]:
            interactables.append(
                self._interactable(
                    "case_clue",
                    strategy["clue_name"],
                    [220, 452],
                    [
                        (strategy["clue_action_label"], "inspect_clue"),
                        ("先记下位置", "wait"),
                    ],
                )
            )
        if not flags["tool_ready"]:
            interactables.append(
                self._interactable(
                    "primary_tool",
                    premise.primary_tool_name,
                    [432, 432],
                    [
                        (strategy["tool_action_label"], "prepare_tool"),
                        ("暂时不碰它", "wait"),
                    ],
                )
            )
        if not flags["support_ready"]:
            interactables.append(
                self._interactable(
                    "support_tool",
                    premise.secondary_tool_name,
                    [1060, 212],
                    [
                        (strategy["support_action_label"], "prepare_support"),
                        ("继续观察动线", "wait"),
                    ],
                )
            )

        interactables.append(self._build_target_interactable(premise, flags, strategy))

        if flags["tool_ready"] and flags["support_ready"]:
            scene_description = "听涛阁的灯光与监控都被你切成了可用的死角，书房像一座精心准备的陷阱。"
        elif flags["support_ready"]:
            scene_description = "书房门外的走廊忽明忽暗，系统延迟开始吞掉别墅原本稳定的秩序。"
        else:
            scene_description = "书房外的空气凝滞而昂贵，听涛阁所有光滑表面都像在替赵万山守口如瓶。"

        return {
            "scene": {
                "background_image": "scene_tingtaoge_blackout.png"
                if flags["support_ready"]
                else "scene_tingtaoge_study.png",
                "bgm": "storm_tension.mp3",
                "description": scene_description,
            },
            "npcs": [
                {
                    "id": "victim",
                    "name": premise.victim_name,
                    "image": "npc_victim.png",
                    "position": victim_position,
                    "patrol": None,
                },
                {
                    "id": "pursuer",
                    "name": premise.detective_name,
                    "image": "npc_pursuer.png",
                    "position": pursuer_position,
                    "patrol": pursuer_patrol,
                },
                {
                    "id": "young_master",
                    "name": "赵少爷",
                    "image": "npc_young_master.png",
                    "position": [702, 238],
                    "patrol": None,
                },
            ],
            "interactables": interactables,
            "narrative": narrative,
            "game_status": "ongoing",
            "ending_text": None,
        }

    def _build_target_interactable(
        self,
        premise: StoryPremise,
        flags: dict[str, bool],
        strategy: dict[str, Any],
    ) -> dict[str, Any]:
        if flags["tool_ready"] and flags["support_ready"]:
            name = strategy["target_name_ready"]
            options = [
                (strategy["clean_action_label"], "execute_clean"),
                ("继续等待更稳的时机", "wait"),
            ]
        elif flags["tool_ready"]:
            name = strategy["target_name_risky"]
            options = [
                (strategy["risky_action_label"], "execute_risky"),
                ("先别暴露企图", "wait"),
            ]
        else:
            name = strategy["target_name_exposed"]
            options = [
                (f"贸然靠近{premise.victim_name}", "rush_target"),
                ("退回阴影里", "wait"),
            ]

        return self._interactable("target_window", name, [916, 352], options)

    def _build_terminal_scene(
        self,
        *,
        premise: StoryPremise,
        game_status: str,
        background_image: str,
        description: str,
        narrative: str,
        ending_text: str,
    ) -> dict[str, Any]:
        return {
            "scene": {
                "background_image": background_image,
                "bgm": "ending_resolve.mp3",
                "description": description,
            },
            "npcs": [
                {
                    "id": "victim",
                    "name": premise.victim_name,
                    "image": "npc_victim.png",
                    "position": [930, 260],
                    "patrol": None,
                },
                {
                    "id": "pursuer",
                    "name": premise.detective_name,
                    "image": "npc_pursuer.png",
                    "position": [420, 250],
                    "patrol": None,
                },
            ],
            "interactables": [],
            "narrative": narrative,
            "game_status": game_status,
            "ending_text": ending_text,
        }

    def _derive_flags(self, history: list[ActionRecord]) -> dict[str, bool]:
        action_ids = {record.action_id for record in history}
        return {
            "clue_checked": "inspect_clue" in action_ids,
            "tool_ready": "prepare_tool" in action_ids,
            "support_ready": "prepare_support" in action_ids,
        }

    def _interactable(
        self,
        interactable_id: str,
        name: str,
        position: list[int],
        options: list[tuple[str, str]],
    ) -> dict[str, Any]:
        return {
            "id": interactable_id,
            "name": name,
            "image": f"{interactable_id}.png",
            "position": position,
            "options": [{"label": label, "action_id": action_id} for label, action_id in options],
        }

    def _build_strategy_copy(self, premise: StoryPremise) -> dict[str, Any]:
        if premise.player_strategy_kind == "facility":
            return {
                "clue_name": "祖宅变卖文件",
                "clue_action_label": "确认地契与变卖安排",
                "clue_narrative": (
                    f"泛黄的地契与电子合同并排躺在抽屉里。只要{premise.victim_name}今晚签完字，"
                    "赵家老宅明天就会被推上拍卖桌。"
                ),
                "tool_action_label": f"把{premise.primary_tool_name}送进备用茶盏",
                "tool_narrative": (
                    f"你借添茶的动作把{premise.primary_tool_name}混进杯中。药性安静得像屋外的雾，"
                    f"只等{premise.victim_name}下一次抿唇。"
                ),
                "support_action_label": f"用{premise.secondary_tool_name}接管书房设备",
                "support_narrative": "你在总控界面里锁定门磁和空调程序，把书房调成一间只剩你知道出口的盒子。",
                "wait_narrative": (
                    f"{premise.player_display_name}几十年的忍耐还没到可以浪费的程度。"
                    f"{premise.victim_name}仍在书房里自顾自地讲话，而你继续像影子一样站着。"
                ),
                "target_name_exposed": f"{premise.victim_name}桌边的明亮破绽",
                "target_name_risky": f"{premise.victim_name}手边的茶盏",
                "target_name_ready": "锁死书房后的无声死角",
                "risky_action_label": f"诱导{premise.victim_name}喝下有问题的茶",
                "clean_action_label": f"锁门后引爆{premise.primary_tool_name}与设备异常",
                "clean_description": "书房的温度与灯光被悄悄调到最不稳定的边缘，昂贵的设备在封闭空间里替你抹平了最后一丝人为痕迹。",
                "clean_narrative": (
                    f"门锁闭合的轻响盖住了药效发作前最后一次呼吸。{premise.victim_name}倒下时，"
                    "整间书房只剩系统报警像一场迟到的暴风雨。"
                ),
                "clean_ending": (
                    f"{premise.detective_name}只能面对一间被智能设备和突发病理共同污染过的书房。"
                    "你保住了老宅，也把自己从第一嫌疑人名单上轻轻挪开。"
                ),
                "risky_status": "special_ending",
                "risky_description": "茶杯滚落在地毯边缘，药效与既往病史迅速纠缠在一起，像一场谁也不愿说透的家族旧疾。",
                "risky_narrative": (
                    f"你没有来得及控制整个房间，只能赌{premise.victim_name}会按旧习惯把茶喝完。"
                    "事情确实发生了，但痕迹没有被完全擦掉。"
                ),
                "risky_ending": "死亡被暂时写成突发性病理反应。你赢得了一条模糊的退路，却还没赢到足够干净的结局。",
                "rush_description": "没有药、没有遮掩、没有后手。你在最明亮的那一秒把自己的敌意直接暴露给了整栋别墅。",
                "rush_narrative": f"你贸然靠近{premise.victim_name}，却被{premise.detective_name}和门口的摄像头动线同时捕捉。",
                "rush_ending": f"{premise.player_role_name}的忠诚和愤怒都是真的，但真实动机并不能替你洗掉仓促留下的痕迹。你失败了。",
            }

        if premise.player_strategy_kind == "digital":
            return {
                "clue_name": "路由器访问日志",
                "clue_action_label": "核对内网拓扑与书房节点",
                "clue_narrative": (
                    "书房的 VR 头显、窗帘电机和生命监测系统都挂在同一条内网链路上。"
                    f"只要切对节点，{premise.victim_name}就会被自己最依赖的设备困住。"
                ),
                "tool_action_label": f"将{premise.primary_tool_name}注入书房网络",
                "tool_narrative": (
                    f"病毒像一滴黑色墨水渗进听涛阁的 Wi-Fi。{premise.victim_name}头上的 VR 设备"
                    "开始吞噬错误数据，仿佛另一层不存在的房间正从屏幕背后长出来。"
                ),
                "support_action_label": f"布置{premise.secondary_tool_name}",
                "support_narrative": (
                    "你把通讯盲区压在书房周围，所有报警与日志上传都慢了半拍。"
                    "这半拍足够让事故看起来像系统自己崩掉。"
                ),
                "wait_narrative": f"{premise.player_display_name}从来不靠冲动赢棋。你盯着听涛阁的网络节点，等它们再多露出一点可下刀的骨架。",
                "target_name_exposed": f"{premise.victim_name}头上的 VR 头显",
                "target_name_risky": f"{premise.victim_name}面前失真的控制界面",
                "target_name_ready": "被盲区包住的书房主节点",
                "risky_action_label": f"直接触发{premise.primary_tool_name}过载",
                "clean_action_label": "在通讯盲区里伪造致命系统故障",
                "clean_description": "VR 画面、室内传感器与门禁回路同时失真，整间书房像被一只看不见的手拖进了延迟与噪点深处。",
                "clean_narrative": (
                    f"{premise.victim_name}被困在自己的设备洪流里，心率和视觉同步失控。"
                    "等通讯恢复时，系统已经替你讲完了第一版死亡经过。"
                ),
                "clean_ending": (
                    f"{premise.detective_name}只能在一堆互相打架的日志里寻找因果。"
                    "你带着真正的商业机密离开，把杀意藏进了一场看似高端设备自毁的事故。"
                ),
                "risky_status": "player_lose",
                "risky_description": "系统确实崩了，但访问日志、异常流量和未清除的节点回写把整条入侵路径钉在了你来过的地方。",
                "risky_narrative": f"没有盲区掩护时，{premise.primary_tool_name}留下的数字足迹比血迹还清楚。",
                "risky_ending": f"{premise.detective_name}顺着日志就能把故障追到你身上。你证明了自己能杀人，却没能证明自己能消失。你失败了。",
                "rush_description": "你没有先拿到系统控制权，就像赤手闯进一间全是摄像头的密室。",
                "rush_narrative": f"你还没来得及改写任何设备，{premise.victim_name}就已经从 VR 画面里摘下头显看向你。",
                "rush_ending": "没有系统掩护的黑客只剩可疑行踪与蹩脚借口。你失败了。",
            }

        if premise.player_strategy_kind == "chemical":
            return {
                "clue_name": "少爷的病历与药单",
                "clue_action_label": "确认药物配方问题",
                "clue_narrative": (
                    "病历里的剂量记录和药厂批次对不上。你知道自己不是在猜测，"
                    f"而是在读一场被{premise.victim_name}默认延续的慢性伤害。"
                ),
                "tool_action_label": f"配制{premise.primary_tool_name}",
                "tool_narrative": "药剂在玻璃管里几乎无色。你只需要一次足够安静的接触，就能让神经反应像被某种旧病突然唤醒。",
                "support_action_label": f"准备{premise.secondary_tool_name}",
                "support_narrative": "你把伪造药瓶放进最顺手的拿取位置。下一次服药动作会看起来和往常完全一样。",
                "wait_narrative": f"{premise.player_role_name}知道真正危险的不是药，而是时间。你收住呼吸，继续等待一个不必解释自己站位的瞬间。",
                "target_name_exposed": f"{premise.victim_name}书桌旁的空档",
                "target_name_risky": f"{premise.victim_name}随手可取的药盒",
                "target_name_ready": "被调包后的服药路径",
                "risky_action_label": f"直接让{premise.primary_tool_name}接触目标",
                "clean_action_label": f"借{premise.secondary_tool_name}完成无声调包",
                "clean_description": "药瓶上的标签、剂量和习惯性动作都没有出错，出错的只有藏在瓶身内部的那一点点命运偏转。",
                "clean_narrative": (
                    f"{premise.victim_name}像往常一样完成了服药动作，整个过程温和得几乎没有戏剧性。"
                    "真正的戏剧性发生在几分钟后，他的神经系统先一步背叛了他。"
                ),
                "clean_ending": (
                    "你保住了能为赵少爷翻案的原始证据，也把目标送进了一场足够像突发疾病的结尾。"
                    f"{premise.detective_name}只能怀疑，却抓不住那次调包发生在何时。"
                ),
                "risky_status": "special_ending",
                "risky_description": "症状发作得很快，快到让人来不及组织一套完整的怀疑，却也快到不够完美。",
                "risky_narrative": "没有替换药瓶的掩护时，你只能赌一次近距离接触不会被回想起来。事情成了，但过程太靠近你本人。",
                "risky_ending": "死亡看起来仍像意外，可只要有人重新拼接时间线，你的身影就会离核心事件太近。这是一场带裂痕的特殊结局。",
                "rush_description": "当你没有药理准备就硬闯过去，温柔与知性的伪装反而成了最不自然的证据。",
                "rush_narrative": f"你直接靠近{premise.victim_name}时，所有人都看得见你没有理由停留那么久。",
                "rush_ending": "没有剂量设计和掩护路径，这场重演只会把你推出去承担全部嫌疑。你失败了。",
            }

        return {
            "clue_name": "赵万山的体检报告",
            "clue_action_label": "校对植入设备参数",
            "clue_narrative": (
                "报告上写满了可以被称作照护、也可以被称作把柄的数字。"
                f"你比谁都清楚{premise.victim_name}那套身体还剩多少冗余。"
            ),
            "tool_action_label": f"准备{premise.primary_tool_name}",
            "tool_narrative": "你把试剂压进便携注射器，剂量刚好位于尸检难以回头确认的边缘。",
            "support_action_label": f"校准{premise.secondary_tool_name}",
            "support_narrative": "脉冲笔在掌心里轻轻震动了一次。只要时机对，植入设备的沉默会比任何语言都更有说服力。",
            "wait_narrative": f"{premise.player_display_name}清楚真正高明的杀人不是速度，而是让所有指标都在死前仍然像一份正常报告。你继续等待。",
            "target_name_exposed": f"{premise.victim_name}座椅旁的治疗空档",
            "target_name_risky": f"{premise.victim_name}手边的问诊死角",
            "target_name_ready": "被医疗权限覆盖的书房角落",
            "risky_action_label": f"只使用{premise.primary_tool_name}模拟病发",
            "clean_action_label": f"联动{premise.primary_tool_name}与{premise.secondary_tool_name}",
            "clean_description": "医疗设备的监测曲线和人体反应被你同时推向同一个方向，像一段早就写好的病程终于在今晚落下句点。",
            "clean_narrative": (
                f"{premise.victim_name}的身体先一步熄火，而植入设备则替你补上了最后的伪证。"
                "等门外的人冲进来，一切都已经像极了医学能够解释的那种失控。"
            ),
            "clean_ending": (
                f"{premise.detective_name}只能得到一份太像自然病程的报告。"
                "你顺手回收了所有会伤到自己的旧账，把整起事件裹进专业权威的外壳里。"
            ),
            "risky_status": "special_ending",
            "risky_description": "症状被成功伪装成了急性病发，但没有设备协同的那部分空白，仍让现场多了一些刺眼的停顿。",
            "risky_narrative": f"你仅靠{premise.primary_tool_name}就把人推过了边界，只是边界附近留下的医学噪点还没有完全安静。",
            "risky_ending": "你完成了杀人，却没完成最漂亮的医学叙事。这是一场足够危险、也足够接近成功的特殊结局。",
            "rush_description": "没有试剂、没有设备、没有权限掩护的医生，只会比普通人更像嫌疑人。",
            "rush_narrative": f"你贸然贴近{premise.victim_name}时，治疗身份立刻变成了最该被追问的借口。",
            "rush_ending": "当专业身份反过来成为指向你的证词，这场实验就已经结束了。你失败了。",
        }


def _premise_to_dict(premise: StoryPremise) -> dict[str, str]:
    return {
        "story_id": premise.story_id,
        "story_title": premise.story_title,
        "story_subtitle": premise.story_subtitle,
        "simulation_operator_name": premise.simulation_operator_name,
        "simulation_background": premise.simulation_background,
        "simulation_briefing": premise.simulation_briefing,
        "player_role_id": premise.player_role_id,
        "player_role_name": premise.player_role_name,
        "player_display_name": premise.player_display_name,
        "player_identity": premise.player_identity,
        "player_strategy_kind": premise.player_strategy_kind,
        "victim_identity": premise.victim_identity,
        "victim_name": premise.victim_name,
        "detective_identity": premise.detective_identity,
        "detective_name": premise.detective_name,
        "setting": premise.setting,
        "motive": premise.motive,
        "initial_goal": premise.initial_goal,
        "hidden_objective": premise.hidden_objective,
        "opening_hook": premise.opening_hook,
        "primary_tool_name": premise.primary_tool_name,
        "secondary_tool_name": premise.secondary_tool_name,
    }
