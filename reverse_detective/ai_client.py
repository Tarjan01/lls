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
            "patrol": None,
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

        completion = client.chat.completions.create(
            model=self._config.model,
            response_format={"type": "json_object"},
            temperature=0.8,
            messages=[
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": self._build_user_prompt(request)},
            ],
        )

        raw_content = self._extract_message_content(completion)
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

    def _extract_message_content(self, completion: Any) -> str:
        choice = completion.choices[0]
        message = getattr(choice, "message", None)
        if message is None:
            raise AIClientError("Live AI response did not contain a message.")

        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "".join(parts)

        raise AIClientError("Live AI message content was empty or not textual.")

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


def build_default_premise() -> StoryPremise:
    """Return the default demo premise used by both mock and live modes."""

    return StoryPremise(
        player_identity="你是赵公馆的私人秘书林岚，擅长维持体面，也擅长隐藏自己的真实意图。",
        victim_identity="赵公馆主人赵铭刚发现你挪用了公馆修缮基金，准备在今晚的遗产说明会上公开账本。",
        detective_identity="侦探顾闻舟以顾问身份受邀到场，正在观察每个人的情绪和站位。",
        setting="暴雨压住了整座山庄的声音，会客厅与书房相连，老旧配电箱时不时发出轻响。",
        motive="如果赵铭在今晚开口，你多年来经营的一切都会崩塌。",
        initial_goal="在不暴露身份的前提下，让赵铭死于一场看似意外或无法指向你的事件。",
    )


class _MockStoryEngine:
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


def _premise_to_dict(premise: StoryPremise) -> dict[str, str]:
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
