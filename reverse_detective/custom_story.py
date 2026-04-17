"""Helpers for player-authored story creation."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import unicodedata
from typing import Any

from reverse_detective.story_loader import DEFAULT_STORIES_DIR, STORY_CONFIG_FILE_NAME


DEFAULT_CUSTOM_STORY_SUBTITLE = "玩家自定义卷宗"
DEFAULT_CUSTOM_DETECTIVE_IDENTITY = "负责复盘此案的侦探"
DEFAULT_ROLE_STRATEGY_KIND = "facility"

_TOP_LEVEL_FIELD_LABELS = {
    "title": "卷宗标题",
    "subtitle": "副标题",
    "location": "案发地点",
    "victim_name": "死者姓名",
    "victim_identity": "死者身份",
    "detective_identity": "追查者身份",
    "setting": "场景设定",
    "core_case": "核心案情",
    "opening_hook": "开场钩子",
}

_TOP_LEVEL_HINTS = {
    "title": "输入卷宗标题，保存后会自动生成新的剧本目录名。",
    "subtitle": "用于卷宗列表展示，可以写风格标签或副标题。",
    "location": "填写案件发生的主舞台，例如美术馆、港口、剧院后台。",
    "victim_name": "填写死者姓名。",
    "victim_identity": "填写死者的身份、职业或社会地位。",
    "detective_identity": "填写追查者的身份描述。",
    "setting": "多行描述案件舞台、限制、时间与环境。",
    "core_case": "多行概述案件本身与玩家要逆向重演的矛盾。",
    "opening_hook": "多行写出把玩家直接拉入最后关键时刻的开场。",
}


@dataclass(slots=True)
class CustomStoryToolDraft:
    name: str = ""
    description: str = ""

    def cleaned(self) -> "CustomStoryToolDraft":
        return CustomStoryToolDraft(
            name=self.name.strip(),
            description=self.description.strip(),
        )


@dataclass(slots=True)
class CustomStoryRoleDraft:
    id: str = ""
    title: str = ""
    name: str = ""
    background: str = ""
    motive: str = ""
    special_conditions: list[str] = field(default_factory=list)
    signature_tools: list[CustomStoryToolDraft] = field(default_factory=list)
    hidden_objective: str = ""
    strategy_kind: str = DEFAULT_ROLE_STRATEGY_KIND

    def cleaned(self) -> "CustomStoryRoleDraft":
        return CustomStoryRoleDraft(
            id=self.id.strip(),
            title=self.title.strip(),
            name=self.name.strip(),
            background=self.background.strip(),
            motive=self.motive.strip(),
            special_conditions=[item.strip() for item in self.special_conditions if item.strip()],
            signature_tools=[
                tool.cleaned()
                for tool in self.signature_tools
                if tool.cleaned().name and tool.cleaned().description
            ],
            hidden_objective=self.hidden_objective.strip(),
            strategy_kind=self.strategy_kind.strip() or DEFAULT_ROLE_STRATEGY_KIND,
        )

    @classmethod
    def starter(cls, index: int) -> "CustomStoryRoleDraft":
        return cls(
            id=f"custom_role_{index + 1}",
            title=f"身份{index + 1}",
            name=f"角色{index + 1}",
            background="补充这个角色与案件、场地、死者之间的关系。",
            motive="补充这个角色必须亲自推进此案的原因。",
            special_conditions=["补充一条该角色独有的便利或限制。"],
            signature_tools=[
                CustomStoryToolDraft(
                    name="招牌工具",
                    description="补充一个与该角色策略强相关的工具、物品或手段。",
                )
            ],
            hidden_objective="补充一个与主线并行的隐藏目标。",
            strategy_kind=DEFAULT_ROLE_STRATEGY_KIND,
        )


@dataclass(frozen=True, slots=True)
class CustomStoryEditorField:
    key: str
    label: str
    kind: str
    value: str
    hint_text: str


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
    roles: list[CustomStoryRoleDraft] = field(default_factory=list)

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
            roles=[role.cleaned() for role in self.roles if role.cleaned().id or role.cleaned().name],
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

    for index, role in enumerate(cleaned.roles):
        _validate_role(role, index)
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
        "roles": (
            [_role_to_payload(role) for role in cleaned.roles]
            if cleaned.roles
            else _build_default_roles(cleaned)
        ),
        "scoring": _build_default_scoring(),
        "rankings": _build_default_rankings(),
    }


def build_custom_story_editor_fields(draft: CustomStoryDraft) -> list[CustomStoryEditorField]:
    fields: list[CustomStoryEditorField] = []
    for field_name in (
        "title",
        "subtitle",
        "location",
        "victim_name",
        "victim_identity",
        "detective_identity",
        "setting",
        "core_case",
        "opening_hook",
    ):
        raw_value = str(getattr(draft, field_name))
        fields.append(
            CustomStoryEditorField(
                key=field_name,
                label=_TOP_LEVEL_FIELD_LABELS[field_name],
                kind="multiline" if field_name in {"setting", "core_case", "opening_hook"} else "text",
                value=raw_value,
                hint_text=_TOP_LEVEL_HINTS[field_name],
            )
        )

    fields.append(
        CustomStoryEditorField(
            key="__action:add_role__",
            label="＋ 添加人物",
            kind="action",
            value="新增一个可编辑角色，包含条件与招牌工具。",
            hint_text="按 Enter 新增一个人物模板；如果不自定义人物，保存时仍会自动生成默认角色。",
        )
    )

    for role_index, role in enumerate(draft.roles):
        role_title = role.name.strip() or role.title.strip() or f"角色{role_index + 1}"
        fields.append(
            CustomStoryEditorField(
                key=f"roles[{role_index}].__summary__",
                label=f"人物 {role_index + 1}",
                kind="readonly",
                value=f"{role_title} | {role.strategy_kind or DEFAULT_ROLE_STRATEGY_KIND}",
                hint_text="按 Delete 可删除当前人物；Enter 不会编辑这一行。",
            )
        )
        for field_name, label, kind, hint in _role_field_specs():
            fields.append(
                CustomStoryEditorField(
                    key=f"roles[{role_index}].{field_name}",
                    label=label,
                    kind=kind,
                    value=str(getattr(role, field_name)),
                    hint_text=hint,
                )
            )

        for condition_index, condition in enumerate(role.special_conditions):
            fields.append(
                CustomStoryEditorField(
                    key=f"roles[{role_index}].special_conditions[{condition_index}]",
                    label=f"条件 {condition_index + 1}",
                    kind="text",
                    value=condition,
                    hint_text="按 Delete 删除这条条件。",
                )
            )
        fields.append(
            CustomStoryEditorField(
                key=f"__action:role:{role_index}:add_condition__",
                label="＋ 添加条件",
                kind="action",
                value="为当前人物补充一条特殊条件。",
                hint_text="按 Enter 添加一条新的特殊条件。",
            )
        )

        for tool_index, tool in enumerate(role.signature_tools):
            fields.append(
                CustomStoryEditorField(
                    key=f"roles[{role_index}].signature_tools[{tool_index}].name",
                    label=f"工具 {tool_index + 1}/名称",
                    kind="text",
                    value=tool.name,
                    hint_text="按 Delete 删除这个工具。",
                )
            )
            fields.append(
                CustomStoryEditorField(
                    key=f"roles[{role_index}].signature_tools[{tool_index}].description",
                    label=f"工具 {tool_index + 1}/描述",
                    kind="multiline",
                    value=tool.description,
                    hint_text="多行描述这个工具如何影响行动、风险或伪装。",
                )
            )
        fields.append(
            CustomStoryEditorField(
                key=f"__action:role:{role_index}:add_tool__",
                label="＋ 添加工具",
                kind="action",
                value="为当前人物补充一个新的招牌工具或关键物品。",
                hint_text="按 Enter 添加一个新的工具模板。",
            )
        )

    return fields


def update_custom_story_field(draft: CustomStoryDraft, field_key: str, raw_value: str) -> str:
    cleaned = _normalize_custom_story_value(field_key, raw_value)
    if field_key in _TOP_LEVEL_FIELD_LABELS:
        setattr(draft, field_key, cleaned)
        return f"{_TOP_LEVEL_FIELD_LABELS[field_key]}已更新。"

    role_match = re.fullmatch(r"roles\[(\d+)\]\.(id|title|name|background|motive|hidden_objective|strategy_kind)", field_key)
    if role_match:
        role = draft.roles[int(role_match.group(1))]
        field_name = role_match.group(2)
        setattr(role, field_name, cleaned)
        return f"{field_name} 已更新。"

    condition_match = re.fullmatch(r"roles\[(\d+)\]\.special_conditions\[(\d+)\]", field_key)
    if condition_match:
        role = draft.roles[int(condition_match.group(1))]
        condition_index = int(condition_match.group(2))
        role.special_conditions[condition_index] = cleaned
        return "人物条件已更新。"

    tool_match = re.fullmatch(
        r"roles\[(\d+)\]\.signature_tools\[(\d+)\]\.(name|description)",
        field_key,
    )
    if tool_match:
        role = draft.roles[int(tool_match.group(1))]
        tool = role.signature_tools[int(tool_match.group(2))]
        field_name = tool_match.group(3)
        setattr(tool, field_name, cleaned)
        return "人物工具已更新。"

    raise ValueError(f"不支持编辑字段 {field_key!r}。")


def apply_custom_story_action(draft: CustomStoryDraft, action_key: str) -> str:
    if action_key == "__action:add_role__":
        draft.roles.append(CustomStoryRoleDraft.starter(len(draft.roles)))
        return "已新增一个人物模板。"

    add_condition_match = re.fullmatch(r"__action:role:(\d+):add_condition__", action_key)
    if add_condition_match:
        role = draft.roles[int(add_condition_match.group(1))]
        role.special_conditions.append("补充一条新的特殊条件。")
        return "已新增一条人物条件。"

    add_tool_match = re.fullmatch(r"__action:role:(\d+):add_tool__", action_key)
    if add_tool_match:
        role = draft.roles[int(add_tool_match.group(1))]
        role.signature_tools.append(
            CustomStoryToolDraft(
                name="新工具",
                description="补充这个工具、物品或资源的用途。",
            )
        )
        return "已新增一个人物工具。"

    raise ValueError(f"不支持的编辑动作 {action_key!r}。")


def remove_custom_story_field(draft: CustomStoryDraft, field_key: str) -> str:
    role_summary_match = re.fullmatch(r"roles\[(\d+)\]\.__summary__", field_key)
    if role_summary_match:
        role_index = int(role_summary_match.group(1))
        removed = draft.roles.pop(role_index)
        return f"已删除人物 {removed.name or removed.title or role_index + 1}。"

    condition_match = re.fullmatch(r"roles\[(\d+)\]\.special_conditions\[(\d+)\]", field_key)
    if condition_match:
        role = draft.roles[int(condition_match.group(1))]
        condition_index = int(condition_match.group(2))
        role.special_conditions.pop(condition_index)
        if not role.special_conditions:
            role.special_conditions.append("补充一条新的特殊条件。")
        return "已删除一条人物条件。"

    tool_name_match = re.fullmatch(r"roles\[(\d+)\]\.signature_tools\[(\d+)\]\.name", field_key)
    tool_desc_match = re.fullmatch(
        r"roles\[(\d+)\]\.signature_tools\[(\d+)\]\.description",
        field_key,
    )
    tool_match = tool_name_match or tool_desc_match
    if tool_match:
        role = draft.roles[int(tool_match.group(1))]
        tool_index = int(tool_match.group(2))
        role.signature_tools.pop(tool_index)
        if not role.signature_tools:
            role.signature_tools.append(
                CustomStoryToolDraft(
                    name="新工具",
                    description="补充这个工具、物品或资源的用途。",
                )
            )
        return "已删除一个人物工具。"

    raise ValueError("当前选中项不支持删除。")


def is_custom_story_editor_key(field_key: str) -> bool:
    if field_key in _TOP_LEVEL_FIELD_LABELS:
        return True
    return field_key.startswith("roles[") or field_key.startswith("__action:")


def _role_field_specs() -> tuple[tuple[str, str, str, str], ...]:
    return (
        ("id", "人物 ID", "text", "用于生成 story.json 的稳定角色标识，建议只用小写字母、数字和下划线。"),
        ("title", "称谓", "text", "例如 馆务总监、私人医生、拍卖对手。"),
        ("name", "人物姓名", "text", "角色在卷宗里的显示名。"),
        ("strategy_kind", "策略标签", "text", "例如 facility / digital / chemical / medical。"),
        ("background", "人物背景", "multiline", "多行补充这个人物与场景、死者、案件的关系。"),
        ("motive", "行动动机", "multiline", "多行补充这个人物为何必须行动。"),
        ("hidden_objective", "隐藏目标", "multiline", "多行补充角色的专属隐藏目标。"),
    )


def _normalize_custom_story_value(field_key: str, raw_value: str) -> str:
    multiline_keys = {
        "setting",
        "core_case",
        "opening_hook",
        "background",
        "motive",
        "hidden_objective",
        "description",
    }
    if field_key == "subtitle":
        return raw_value.strip() or DEFAULT_CUSTOM_STORY_SUBTITLE
    if field_key == "detective_identity":
        return raw_value.strip() or DEFAULT_CUSTOM_DETECTIVE_IDENTITY
    if any(key in field_key for key in multiline_keys):
        return raw_value.replace("\r\n", "\n").replace("\r", "\n").strip()
    return raw_value.replace("\r", " ").replace("\n", " ").strip()


def _validate_role(role: CustomStoryRoleDraft, index: int) -> None:
    label_prefix = f"人物 {index + 1}"
    required_values = {
        "id": "ID",
        "title": "称谓",
        "name": "姓名",
        "background": "背景",
        "motive": "动机",
        "hidden_objective": "隐藏目标",
        "strategy_kind": "策略标签",
    }
    for field_name, label in required_values.items():
        if not getattr(role, field_name):
            raise ValueError(f"{label_prefix}{label}不能为空。")
    if not role.special_conditions:
        raise ValueError(f"{label_prefix}至少需要一条特殊条件。")
    if not role.signature_tools:
        raise ValueError(f"{label_prefix}至少需要一个招牌工具。")
    for condition_index, condition in enumerate(role.special_conditions):
        if not condition:
            raise ValueError(f"{label_prefix}的条件 {condition_index + 1} 不能为空。")
    for tool_index, tool in enumerate(role.signature_tools):
        if not tool.name or not tool.description:
            raise ValueError(f"{label_prefix}的工具 {tool_index + 1} 需要完整名称和描述。")


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


def _role_to_payload(role: CustomStoryRoleDraft) -> dict[str, Any]:
    return {
        "id": role.id,
        "title": role.title,
        "name": role.name,
        "background": role.background,
        "motive": role.motive,
        "special_conditions": list(role.special_conditions),
        "signature_tools": [
            {
                "name": tool.name,
                "description": tool.description,
            }
            for tool in role.signature_tools
        ],
        "hidden_objective": role.hidden_objective,
        "strategy_kind": role.strategy_kind,
    }


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
                "会在今夜彻底失控。"
            ),
            "special_conditions": [
                f"掌握{location_ref}内务、门禁或后勤层面的通行优势。",
                "熟悉现场巡查节奏、备用路线与临时封控手段。",
            ],
            "signature_tools": [
                {
                    "name": "通行总卡",
                    "description": "能够快速切换门禁、储物区和后勤通道权限，用于制造短暂的行动窗口。",
                },
                {
                    "name": "后勤控制台",
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
                "能够快速判断哪些证据、记录或公开说辞最适合被反向利用。",
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
                f"你确信如果今夜不断开局面，{case_ref}"
                "只会让更多人替对方承担后果。"
            ),
            "special_conditions": [
                "拥有看起来最合理的近身理由，不容易第一时间引发警觉。",
                "擅长把异常伪装成流程失误、身体意外或管理疏漏。",
            ],
            "signature_tools": [
                {
                    "name": "应急诊疗笔",
                    "description": "外观像普通记录工具，实际适合执行短促、隐蔽的近身操作。",
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
