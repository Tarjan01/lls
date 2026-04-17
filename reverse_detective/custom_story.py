"""Helpers for player-authored story creation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import unicodedata
from typing import Any

from reverse_detective.story_loader import DEFAULT_STORIES_DIR, STORY_CONFIG_FILE_NAME


DEFAULT_CUSTOM_STORY_SUBTITLE = "玩家自定义卷宗"
DEFAULT_CUSTOM_DETECTIVE_IDENTITY = "负责复盘此案的侦探"


@dataclass(slots=True)
class CustomStoryDraft:
    title: str = ""
    subtitle: str = DEFAULT_CUSTOM_STORY_SUBTITLE
    location: str = ""
    setting: str = ""
    core_case: str = ""
    opening_hook: str = ""
    victim_name: str = ""
    victim_identity: str = ""
    detective_identity: str = DEFAULT_CUSTOM_DETECTIVE_IDENTITY

    @classmethod
    def blank(cls) -> "CustomStoryDraft":
        return cls()

    def cleaned(self) -> "CustomStoryDraft":
        return CustomStoryDraft(
            title=self.title.strip(),
            subtitle=self.subtitle.strip() or DEFAULT_CUSTOM_STORY_SUBTITLE,
            location=self.location.strip(),
            setting=self.setting.strip(),
            core_case=self.core_case.strip(),
            opening_hook=self.opening_hook.strip(),
            victim_name=self.victim_name.strip(),
            victim_identity=self.victim_identity.strip(),
            detective_identity=self.detective_identity.strip() or DEFAULT_CUSTOM_DETECTIVE_IDENTITY,
        )


def validate_custom_story_draft(draft: CustomStoryDraft) -> CustomStoryDraft:
    cleaned = draft.cleaned()
    required_fields = {
        "title": "卷宗标题",
        "location": "案发地点",
        "setting": "场景设定",
        "core_case": "核心案情",
        "opening_hook": "开场钩子",
        "victim_name": "死者姓名",
        "victim_identity": "死者身份",
    }
    for field_name, label in required_fields.items():
        if not getattr(cleaned, field_name):
            raise ValueError(f"{label}不能为空。")
    return cleaned


def write_custom_story(
    draft: CustomStoryDraft,
    *,
    detective_name: str,
    stories_dir: Path | None = None,
) -> tuple[Path, str]:
    cleaned = validate_custom_story_draft(draft)
    root = (stories_dir or DEFAULT_STORIES_DIR).resolve()
    story_id = _allocate_story_id(cleaned.title, root)
    story_dir = root / story_id
    story_dir.mkdir(parents=True, exist_ok=False)

    payload = build_custom_story_payload(
        cleaned,
        story_id=story_id,
        detective_name=detective_name.strip() or "江川",
    )
    story_path = story_dir / STORY_CONFIG_FILE_NAME
    story_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return story_path, story_id


def build_custom_story_payload(
    draft: CustomStoryDraft,
    *,
    story_id: str,
    detective_name: str,
) -> dict[str, Any]:
    cleaned = validate_custom_story_draft(draft)
    return {
        "id": story_id,
        "title": cleaned.title,
        "subtitle": cleaned.subtitle,
        "case": {
            "location": cleaned.location,
            "setting": cleaned.setting,
            "core_case": cleaned.core_case,
            "opening_hook": cleaned.opening_hook,
            "victim": {
                "name": cleaned.victim_name,
                "identity": cleaned.victim_identity,
            },
            "pursuer": {
                "name": detective_name.strip() or "江川",
                "identity": cleaned.detective_identity,
            },
        },
        "roles": _build_default_roles(cleaned),
        "scoring": _build_default_scoring(),
        "rankings": _build_default_rankings(),
    }


def _allocate_story_id(title: str, stories_dir: Path) -> str:
    slug_root = _slugify_title(title)
    candidate = slug_root
    suffix = 2
    while (stories_dir / candidate).exists():
        candidate = f"{slug_root}_{suffix}"
        suffix += 1
    return candidate


def _slugify_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_slug = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    if ascii_slug:
        return ascii_slug

    compact = re.sub(r"\s+", "", title)
    codepoints = "".join(f"{ord(char):x}" for char in compact[:4]) or "story"
    return f"custom_story_{codepoints[:16]}"


def _build_default_roles(draft: CustomStoryDraft) -> list[dict[str, Any]]:
    victim_ref = f"{draft.victim_name}这名{draft.victim_identity}"
    location_ref = draft.location
    case_ref = draft.core_case
    setting_ref = draft.setting

    return [
        {
            "id": "inside_operator",
            "title": "内部人",
            "name": "值守管理员",
            "background": (
                f"你长期在{location_ref}负责通行、后勤与现场秩序，比任何人都熟悉这里的盲区与备用通道。"
                f"最近你意识到，{victim_ref}正在把整件事推进到一个无法回头的地步：{setting_ref}"
            ),
            "motive": (
                f"你相信只要让{draft.victim_name}继续掌控局面，{case_ref}"
                "会在今晚彻底失控。"
            ),
            "special_conditions": [
                f"掌握{location_ref}内务、门禁或后勤层面的通行优势。",
                "熟悉现场巡查节奏、备用路线与临时封控手段。",
            ],
            "signature_tools": [
                {
                    "name": "通行总卡",
                    "description": "能快速切换门禁、储物区和后勤通道权限，用于制造短暂的行动窗口。",
                },
                {
                    "name": "后勤控制板",
                    "description": "可临时调节灯光、遮挡或设备状态，让现场动线出现可预测的空档。",
                },
            ],
            "hidden_objective": "在离开前保住现场里最不该外流的一份内部记录或关键物件。",
            "strategy_kind": "facility",
        },
        {
            "id": "outside_rival",
            "title": "竞争者",
            "name": "旧日对手",
            "background": (
                f"你与{draft.victim_name}在利益、名誉或资源上缠斗已久。"
                f"这一次，你知道{location_ref}里的局面并不稳固，而{setting_ref}"
            ),
            "motive": (
                f"你不只是想让{draft.victim_name}消失，更想让{case_ref}"
                "看起来像是对方自己一步步逼出来的崩塌。"
            ),
            "special_conditions": [
                "擅长借外部资源、伪装身份或临时权限混入现场。",
                "能快速判断哪些证据、记录或公开说辞最适合被反向利用。",
            ],
            "signature_tools": [
                {
                    "name": "伪造凭证",
                    "description": "可在短时间内伪装访客、合作方或临时来宾的出入依据。",
                },
                {
                    "name": "信号干扰器",
                    "description": "能够短暂打乱局部通信与记录同步，制造几分钟的噪声带。",
                },
            ],
            "hidden_objective": "趁混乱拿走一份能改写双方关系或利益格局的关键材料。",
            "strategy_kind": "digital",
        },
        {
            "id": "close_adviser",
            "title": "近身顾问",
            "name": "贴身顾问",
            "background": (
                f"你以顾问、助理或长期协作者的身份接近{draft.victim_name}，"
                f"因此最清楚对方在{location_ref}里的习惯与脆弱点。{setting_ref}"
            ),
            "motive": (
                f"你知道{case_ref}背后真正的代价，而{draft.victim_name}"
                "从未打算为此停手。"
            ),
            "special_conditions": [
                "更容易获得近身交流、递送物品或提前布置现场细节的机会。",
                "熟悉受害者的习惯路线、停留点和临场反应。",
            ],
            "signature_tools": [
                {
                    "name": "替换套件",
                    "description": "能够把桌面物件、包装或常用品做无声替换，改变细节走向。",
                },
                {
                    "name": "掩护香雾",
                    "description": "可短时间遮住气味、痕迹或近距离动作留下的异常感。",
                },
            ],
            "hidden_objective": "把最能证明你曾近身接触过关键区域的痕迹全部带走。",
            "strategy_kind": "chemical",
        },
        {
            "id": "private_doctor",
            "title": "专业人士",
            "name": "私人医顾",
            "background": (
                f"你以医疗、安保、法务或技术顾问的身份介入过{draft.victim_name}的日常安排，"
                f"因此对{location_ref}里那些看似正常的流程格外敏感。{setting_ref}"
            ),
            "motive": (
                f"你确信如果今晚不截断局面，{case_ref}"
                "只会让更多人替对方承担后果。"
            ),
            "special_conditions": [
                "拥有看起来最合理的近身理由，不容易第一时间引发警觉。",
                "擅长把异常伪装成流程失误、身体意外或管理疏漏。",
            ],
            "signature_tools": [
                {
                    "name": "应急诊疗笔",
                    "description": "外观看似普通记录工具，实则适合执行短促、隐蔽的近身操作。",
                },
                {
                    "name": "记录回收袋",
                    "description": "用于快速收拢便签、处置记录或一次性痕迹，减少遗留物。",
                },
            ],
            "hidden_objective": "在结算前回收所有会把你的专业身份与现场异常连起来的记录。",
            "strategy_kind": "medical",
        },
    ]


def _build_default_scoring() -> dict[str, Any]:
    return {
        "base_score": 60,
        "evidence_penalties": [
            {
                "title": "凶器或工具遗留",
                "description": "把专属工具、替换物或明显不该出现的物件留在了现场。",
                "score_delta": -20,
            },
            {
                "title": "关键目击暴露",
                "description": "被现场人员、监控补帧或近距离证词锁定了关键行动。",
                "score_delta": -20,
            },
            {
                "title": "时间线破绽",
                "description": "行动顺序、出入时间或伪装说辞之间出现了明显矛盾。",
                "score_delta": -20,
            },
        ],
        "task_bonuses": [
            {
                "title": "隐藏任务完成",
                "description": "达成所选身份的专属隐藏目标。",
                "score_delta": 15,
            },
            {
                "title": "无声推进",
                "description": "全程未触发明显警报，也没有出现失控追逐。",
                "score_delta": 10,
            },
            {
                "title": "速通收束",
                "description": "在较短回合内完成布局、行动与撤离。",
                "score_delta": 10,
            },
            {
                "title": "痕迹清理",
                "description": "没有留下显眼的指向性线索。",
                "score_delta": 5,
            },
        ],
    }


def _build_default_rankings() -> list[dict[str, str]]:
    return [
        {
            "rank": "S级 - 完美收束",
            "score_range": "90分以上",
            "description": "整场重演被你压进了最安静的版本，调查者几乎无法拼回完整真相。",
        },
        {
            "rank": "A级 - 高效执行",
            "score_range": "70-89分",
            "description": "你完成了目标并保住了大部分伪装，只留下少量值得追问的裂缝。",
        },
        {
            "rank": "B级 - 勉强过关",
            "score_range": "60-69分",
            "description": "剧本被推进到了结局，但现场仍残留足以继续追查的痕迹。",
        },
        {
            "rank": "失败 - 破绽过多",
            "score_range": "60分以下",
            "description": "行动虽然发生了，但你留下了太多能回指自身的证据。",
        },
    ]
