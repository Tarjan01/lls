# 场景交互结构化存储方案（草案）

这份文档的目标很简单：把“背景图、可互动物、可见选项、选项后果、背包条件、场景状态”拆成清楚、可落盘、可加载的结构。这样程序只要读 JSON，就能知道当前场景里该显示什么、能点什么、点完会发生什么。

## 1. 为什么要分三层

可以把它理解成“地图、存档、规则书”。

### 1.1 场景静态定义

这一层只描述“这个场景长什么样、有哪些可交互点、默认状态是什么”。它是地图蓝图，不关心玩家现在有没有钥匙、已经做过什么、前一秒刚点了哪个按钮。

适合放进去的内容有：

- 背景图
- 场景名字、场景 id
- 场景内的门、柜子、抽屉、NPC、证物点
- 每个物体的默认位置、默认状态、默认可选项
- 每个物体的规则入口

这一层应该是“同一张图，所有玩家都共用”的。

### 1.2 运行时状态

这一层是“当前这一局到底打到了什么程度”。它是存档，不是地图。

适合放进去的内容有：

- 玩家背包
- 全局剧情标记
- 当前场景内各个物体的状态
- 已访问过哪些场景
- 当前回合数、历史记录

这一层会随着玩家操作不断变化，需要保存和恢复。

### 1.3 交互规则

这一层决定“某个选项现在要不要显示、点了以后会发生什么”。它是规则书。

它通常会同时读取：

- 场景静态定义
- 运行时状态
- 当前场景的物体状态

然后输出：

- 当前可显示的选项
- 当前可执行的选项
- 选项执行后的状态变化

最关键的一点是：

- `show_if` 负责“显示不显示”
- `local_logic` 负责“本地能不能直接处理”
- `effects` 负责“处理成功后改什么”

这样就能做到“有钥匙才显示开门选项”“门已经开了就不再显示上锁选项”“拿到手套后才出现翻找证物的选项”。

## 2. 场景图与 scene_id 对照

建议每张背景图都对应一个稳定的 `scene_id`。这样程序不用猜图名，只按 id 找定义。

| scene_id | background_image | 含义 |
| --- | --- | --- |
| `main_overview` | `总.jpg` | 主场景总览 |
| `front_hall` | `前厅.png` | 前厅 |
| `study` | `书房.jpg` | 书房 |
| `tea_room` | `茶水间.png` | 茶水间 |
| `infirmary` | `医务室.png` | 医务室 |
| `storage` | `杂物间.png` | 杂物间 |
| `master_bedroom` | `主卧.png` | 主卧 |
| `young_master_bedroom` | `少爷卧室.png` | 少爷卧室 |
| `guest_room` | `苏曼客房.png` | 客房 |
| `attic` | `阁楼.png` | 阁楼 |

建议所有 `background_image` 都只从 `assets/h_ass/` 里选。

## 3. 建议的文件组织

```text
scenes/
  index.json
  main_overview.json
  front_hall.json
  study.json
  tea_room.json
  ...

saves/
  save_001.json
  save_002.json
```

推荐再加一个索引文件：

```json
{
  "schema_version": "1.0",
  "scenes": [
    { "scene_id": "main_overview", "file": "main_overview.json" },
    { "scene_id": "front_hall", "file": "front_hall.json" },
    { "scene_id": "study", "file": "study.json" }
  ]
}
```

这样加载时只需要先查索引，再按 `scene_id` 读对应场景文件。

## 4. JSON Schema 草案

下面不是严格机器验证版的最终 schema，而是“后续很容易直接转成正式 schema”的落盘草案。

### 4.1 SceneDefinition

```json
{
  "schema_version": "1.0",
  "scene_id": "front_hall",
  "scene_name": "前厅",
  "background_image": "前厅.png",
  "bgm": "crime_suspense_medium",
  "description": "前厅里光线很暗，门口的脚印还没有干。",
  "spawn": {
    "player": { "x": 0.12, "y": 0.82, "facing": "right" }
  },
  "npcs": [],
  "interactables": []
}
```

字段说明：

- `schema_version`：版本号，方便以后升级格式。
- `scene_id`：场景稳定 id，程序内部用它查文件。
- `scene_name`：给人看的名称。
- `background_image`：背景图文件名，只放图名，不放路径。
- `bgm`：场景音乐 id。
- `description`：场景文字说明，通常给 AI 和日志用。
- `spawn.player`：玩家进入场景后的出生点，建议用 0 到 1 的归一化坐标。
- `npcs`：NPC 定义列表。
- `interactables`：可互动物定义列表。

### 4.2 Interactable

```json
{
  "id": "study_door",
  "name": "书房门",
  "kind": "door",
  "image": "locked_door.png",
  "hotspot": { "type": "rect", "x": 0.68, "y": 0.31, "w": 0.12, "h": 0.27 },
  "default_state": {
    "opened": false,
    "locked": true,
    "hidden": false,
    "disabled": false
  },
  "options": []
}
```

字段说明：

- `id`：物体稳定 id。
- `name`：显示给玩家看的名字。
- `kind`：物体类型，建议值如 `door`、`prop`、`container`、`clue`、`npc`。
- `image`：场景中展示的小图标或贴图，可选。
- `hotspot`：触发区域，建议用归一化矩形。
- `default_state`：物体默认状态，必须包含 `opened`、`locked`、`hidden`、`disabled`。
- `options`：这个物体的交互选项列表。

### 4.3 Option

```json
{
  "id": "unlock_with_key",
  "label": "用书房钥匙开门",
  "priority": 20,
  "resolution_mode": "local_rule",
  "show_if": {
    "all": [
      { "has_item": { "item_id": "study_key", "count_gte": 1 } },
      { "entity_state": { "entity_id": "study_door", "state": { "locked": true } } }
    ]
  },
  "local_logic": {
    "requires_state": { "locked": true },
    "set_state": { "locked": false, "opened": true },
    "success_text": "钥匙转动，门锁打开了。",
    "failure_text": "门现在已经不需要这把钥匙了。"
  },
  "effects": [
    { "type": "consume_item", "item_id": "study_key", "count": 1 },
    { "type": "set_flag", "key": "front_hall.study_door_opened", "value": true },
    { "type": "switch_scene", "scene_id": "study" }
  ],
  "sfx": "lock_open"
}
```

字段说明：

- `id`：选项稳定 id。
- `label`：按钮文案。
- `priority`：排序权重，数值越小越靠前。
- `resolution_mode`：`local_rule` 或 `immediate_ai`。
- `show_if`：决定选项是否显示。
- `local_logic`：本地确定性处理逻辑。
- `effects`：成功后产生的后果。
- `sfx`：点击后播放的音效 id。

### 4.4 Condition

`show_if` 建议支持如下组合语法：

```json
{ "all": [ ... ] }
{ "any": [ ... ] }
{ "not": { ... } }
{ "has_item": { "item_id": "study_key", "count_gte": 1 } }
{ "flag": { "key": "front_hall.study_door_opened", "value": true } }
{ "entity_state": { "entity_id": "study_door", "state": { "locked": true } } }
{ "scene_visited": { "scene_id": "front_hall" } }
{ "turn_gte": 3 }
```

说明：

- `all`：全部满足才显示。
- `any`：满足任意一个就显示。
- `not`：取反。
- `has_item`：背包里有没有某个物品。
- `flag`：全局剧情标记。
- `entity_state`：当前场景或指定物体的状态。
- `scene_visited`：是否来过某个场景。
- `turn_gte`：回合数门槛。

### 4.5 Effect

`effects` 建议支持如下原子动作：

```json
{ "type": "set_state", "target": "self", "set": { "locked": false, "opened": true } }
{ "type": "set_state", "target": "entity:tea_table", "set": { "disabled": true } }
{ "type": "set_flag", "key": "front_hall.study_door_examined", "value": true }
{ "type": "add_item", "item_id": "guest_register", "count": 1 }
{ "type": "consume_item", "item_id": "study_key", "count": 1 }
{ "type": "switch_scene", "scene_id": "study", "entry_point_id": "default" }
{ "type": "append_log", "kind": "scene", "text": "你记住了门锁上的划痕。" }
```

说明：

- `set_state`：改当前物体或指定物体状态。
- `set_flag`：改全局标记。
- `add_item` / `consume_item`：改背包。
- `switch_scene`：切换场景。
- `append_log`：写入反馈文本。

## 5. 完整示例

下面这个例子用 `前厅.png` 作为背景，演示“同一个物体的选项会因为背包和标记变化而变化”。

### 5.1 场景定义：`front_hall.json`

```json
{
  "schema_version": "1.0",
  "scene_id": "front_hall",
  "scene_name": "前厅",
  "background_image": "前厅.png",
  "bgm": "crime_suspense_medium",
  "description": "前厅安静得过分，门锁和茶几都像在等人先开口。",
  "spawn": {
    "player": { "x": 0.18, "y": 0.84, "facing": "right" }
  },
  "npcs": [],
  "interactables": [
    {
      "id": "study_door",
      "name": "书房门",
      "kind": "door",
      "image": "locked_door.png",
      "hotspot": { "type": "rect", "x": 0.67, "y": 0.30, "w": 0.13, "h": 0.28 },
      "default_state": {
        "opened": false,
        "locked": true,
        "hidden": false,
        "disabled": false
      },
      "options": [
        {
          "id": "inspect_lock",
          "label": "检查门锁",
          "priority": 10,
          "resolution_mode": "local_rule",
          "show_if": { "all": [] },
          "local_logic": {
            "requires_state": {},
            "set_state": {},
            "success_text": "门锁上有细微划痕，像是刚被人试过。",
            "failure_text": "这扇门已经没有新的东西可检查了。"
          },
          "effects": [
            { "type": "set_flag", "key": "front_hall.study_lock_examined", "value": true }
          ],
          "sfx": "ui_confirm"
        },
        {
          "id": "open_with_key",
          "label": "用书房钥匙开门",
          "priority": 20,
          "resolution_mode": "local_rule",
          "show_if": {
            "all": [
              { "has_item": { "item_id": "study_key", "count_gte": 1 } },
              { "entity_state": { "entity_id": "study_door", "state": { "locked": true } } }
            ]
          },
          "local_logic": {
            "requires_state": { "locked": true },
            "set_state": { "locked": false, "opened": true },
            "success_text": "钥匙转动后，书房门被打开了。",
            "failure_text": "门已经不是锁着的状态了。"
          },
          "effects": [
            { "type": "consume_item", "item_id": "study_key", "count": 1 },
            { "type": "switch_scene", "scene_id": "study", "entry_point_id": "door" }
          ],
          "sfx": "lock_open"
        },
        {
          "id": "knock_door",
          "label": "敲门",
          "priority": 30,
          "resolution_mode": "immediate_ai",
          "show_if": { "all": [] },
          "ai_hint": "敲门可能引出房内人的反应，改变警觉度或剧情走向。",
          "sfx": "door_open"
        }
      ]
    },
    {
      "id": "tea_table",
      "name": "茶几",
      "kind": "clue",
      "image": "round_table.png",
      "hotspot": { "type": "rect", "x": 0.35, "y": 0.60, "w": 0.14, "h": 0.16 },
      "default_state": {
        "opened": false,
        "locked": false,
        "hidden": false,
        "disabled": false
      },
      "options": [
        {
          "id": "read_note",
          "label": "查看茶几上的字条",
          "priority": 10,
          "resolution_mode": "local_rule",
          "show_if": { "all": [] },
          "local_logic": {
            "requires_state": {},
            "set_state": { "opened": true },
            "success_text": "字条上写着：今晚不要去阁楼。",
            "failure_text": "这张字条已经被看过了。"
          },
          "effects": [
            { "type": "set_flag", "key": "front_hall.note_seen", "value": true }
          ],
          "sfx": "ui_success"
        },
        {
          "id": "take_register",
          "label": "取走访客登记册",
          "priority": 20,
          "resolution_mode": "local_rule",
          "show_if": {
            "all": [
              { "flag": { "key": "front_hall.study_lock_examined", "value": true } },
              { "not": { "flag": { "key": "front_hall.register_taken", "value": true } } }
            ]
          },
          "local_logic": {
            "requires_state": {},
            "set_state": { "disabled": true },
            "success_text": "你把登记册收进了口袋。",
            "failure_text": "登记册已经不在这里了。"
          },
          "effects": [
            { "type": "add_item", "item_id": "guest_register", "count": 1 },
            { "type": "set_flag", "key": "front_hall.register_taken", "value": true }
          ],
          "sfx": "ui_confirm"
        }
      ]
    }
  ]
}
```

### 5.2 运行时状态：`save_001.json`

```json
{
  "schema_version": "1.0",
  "story_id": "tingtaoge_last_night",
  "current_scene_id": "front_hall",
  "turn_index": 3,
  "inventory": [
    { "item_id": "study_key", "name": "书房钥匙", "count": 1 },
    { "item_id": "flashlight", "name": "手电筒", "count": 1 }
  ],
  "global_flags": {
    "front_hall.study_lock_examined": true,
    "front_hall.note_seen": true,
    "front_hall.register_taken": false
  },
  "scene_state": {
    "front_hall": {
      "study_door": {
        "opened": false,
        "locked": true,
        "hidden": false,
        "disabled": false
      },
      "tea_table": {
        "opened": true,
        "locked": false,
        "hidden": false,
        "disabled": false
      }
    }
  },
  "visited_scenes": ["main_overview", "front_hall"]
}
```

### 5.3 这个状态下，程序应该显示什么

对 `study_door` 来说：

- `检查门锁` 显示
- `用书房钥匙开门` 显示，因为背包里有 `study_key`，而且门仍然是 `locked=true`
- `敲门` 显示

对 `tea_table` 来说：

- `查看茶几上的字条` 显示
- `取走访客登记册` 显示，因为已经满足 `front_hall.study_lock_examined=true`

如果再把 `study_key` 从背包里移走：

- `用书房钥匙开门` 就会消失

如果把 `study_door.locked` 改成 `false`：

- `用书房钥匙开门` 也会消失

这就是“选项会随着外界条件改变而改变”的核心。

## 6. 和现有代码怎么接

建议加载链路这样走：

1. 先按 `scene_id` 读取场景定义。
2. 再读取当前存档里的运行时状态。
3. 合并场景默认状态和运行时状态。
4. 遍历 `interactables`。
5. 用 `show_if` 过滤出当前可显示的选项。
6. 玩家点选后：
   - 先执行 `local_logic`
   - 再执行 `effects`
   - 再刷新一次选项可见性

对应到现有代码的直觉映射大致是：

- `scene_loader.py` 负责读场景定义
- `game_state.py` 负责维护运行时状态
- `local_logic.py` 负责条件过滤和本地规则
- `renderer.py` 负责把背景图和选项画出来

如果后面要继续扩展，也建议优先保持这三层不混在一起，这样场景图、存档和规则都能独立维护。
