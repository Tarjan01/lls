# Reverse Detective
反转型侦探游戏(Reverse Detective)
本文档对该游戏相关名词和玩法进行解释和说明。

## 核心内容
玩家扮演凶手，在系统给定的人物设定、故事背景等条件和限制下，尝试达成行凶目标而不被发现。
本质上是一个"文字 AI 互动游戏 + 图形交互界面"的融合形态：叙事与逻辑由大模型驱动，玩家通过 Pygame 图形界面进行交互。

## 游戏流程
1. **开局生成**：游戏启动时，AI 根据预设的基础设定（玩家身份、受害者身份、事件背景、动机）一次性生成初始场景配置，以 JSON 格式返回，客户端解析后加载场景。
2. **场景探索**：玩家控制人物在 2.5D Pygame 场景中移动。NPC（含受害者）以静态站立为主，条件允许时可加入简单巡逻路径。
3. **物品交互**：玩家靠近可互动物品时，弹出选项框。玩家做出选择后，客户端将【当前游戏状态 + 玩家选择】发送给 AI，AI 返回新的场景状态 JSON，客户端据此更新界面。
4. **结局判定**：每次 AI 返回时，JSON 中包含 `game_status` 字段，可能值为 `ongoing` / `player_win` / `player_lose` / `special_ending`。结局文本由 AI 生成，支持多种结局分支。

## 胜负条件
- **玩家胜利**：成功达成行凶目标且未被侦探识破，AI 判定案件悬而未决。
- **玩家失败**：侦探查案成功，玩家身份暴露。
- **特殊结局**：由 AI 根据玩家行为动态生成，例如意外事故、嫁祸他人成功等分支。

## 场景 JSON 结构（Schema）
AI 每次返回的 JSON 需严格遵循以下结构：

```json
{
    "scene": {
        "background_image": "scene_living_room.png",
        "bgm": "tense_ambient.mp3",
        "description": "昏暗的客厅，窗外雨声不断。"
    },
    "npcs": [
    {
        "id": "victim_01",
        "name": "李明",
        "image": "npc_victim.png",
        "position": [300, 400],
        "patrol": null
    }
    ],
    "interactables": [
        {
            "id": "item_knife",
            "name": "厨刀",
            "image": "item_knife.png",
            "position": [500, 350],
            "options": [
            {"label": "拿起厨刀", "action_id": "pick_up_knife"},
            {"label": "假装没看见", "action_id": "ignore_knife"}
            ]
        }
    ],
    "narrative": "你独自站在客厅中央，时间不多了。",
    "game_status": "ongoing",
    "ending_text": null
}
```
## 关键内容
游戏制作方只提供基础的人物设定和故事背景。场景图片、可互动物品、选项内容、故事逻辑与结局**全部由大模型实时生成**。