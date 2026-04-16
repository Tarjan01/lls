# 开发说明

## 定义
该项目是一个游戏项目的 demo 版本，旨在快速实现核心玩法，形成展示用 demo。
该项目暂时不需要考虑过多的用户体验，暂时不会公开给大众进行游玩。
README.md 包含了最新的游戏玩法说明。在更新玩法时，可以使用 `git diff` 的方式了解最新的玩法变更，据此实现代码更新。

## 开发环境
- 本项目统一使用 `uv` 管理 Python 环境、依赖、脚本入口和测试。
- 首次进入仓库后，优先执行 `uv sync --dev` 初始化开发环境。
- 启动游戏时，优先使用 `uv run game`，不要默认直接执行 `python main.py`。
- 运行测试时，优先使用 `uv run pytest`。
- 新增运行时依赖时，优先使用 `uv add <dependency>`；新增开发依赖时，优先使用 `uv add --dev <dependency>`。
- 除非有明确理由，否则不要混用 `pip install`、手动虚拟环境和其他 Python 依赖管理方式。

## 技术选型
- **图形框架**：统一使用 `pygame`，不使用 tkinter、arcade 或其他图形库。
- **AI 调用**：使用 `openai` SDK，base_url 指向配置文件中的 `crs` provider。
- **配置加载**：`config.toml` 放于项目根目录，`credentials.json` 放于 `~/.reverse_detective/credentials.json`（避免提交到仓库）。

## 工程约束
- 根目录 `main.py` 只保留脚本入口和兼容性导出；实际实现必须放在 `reverse_detective/` 包内（注意：包名全小写加下划线，不含空格）。
- 通用工具函数放在 `reverse_detective/utils/`；场景渲染逻辑放在 `reverse_detective/renderer.py`；游戏状态管理放在 `reverse_detective/game_state.py`。
- **AI 调用必须统一封装在 `reverse_detective/ai_client.py`**，其他模块不得直接调用 openai SDK。`ai_client.py` 负责构造 prompt、发送请求、解析返回的 JSON、处理异常。
- 场景 JSON 的解析和校验逻辑统一放在 `reverse_detective/scene_loader.py`，AI 返回的原始 JSON 必须经过 schema 校验后才能传入渲染层。
- Pygame 主循环、事件处理、渲染调用不要堆在同一文件；当函数超过 100 行或文件明显失去可读性时，优先拆模块。
- 已废弃的交互路径要同步删除，不要长期保留"双轨实现"；保留旧路径前必须说明原因，并把缺口记录到 `MVP_TECH_DEBT.md`。
- 任何新增规则如果只在一处实现而未同步，必须先说明原因，并记录到 `MVP_TECH_DEBT.md`。

## AI 调用约束
- 每次玩家做出选项选择后，触发一次 AI 调用，传入【初始设定 + 完整历史操作记录 + 本次选择】。
- AI 必须返回符合 README.md 中定义的场景 JSON schema 的内容，**不得返回纯文本或 markdown 格式**。
- prompt 中须明确要求 AI 只返回 JSON，不包含任何前缀说明或 markdown 代码块。
- AI 返回的 `game_status` 字段决定游戏流程走向，渲染层根据此字段决定是否展示结局画面。
- AI 调用过程中需展示 loading 状态，防止界面假死。

## 玩法实现约束
- NPC 默认为静态，坐标固定在 JSON 的 `position` 字段中。
- 若 NPC 的 `patrol` 字段不为 null，则按给定路径列表进行简单线性巡逻。
- 玩家角色碰撞检测基于矩形（pygame.Rect），不需要像素级精度。
- 选项弹窗在玩家进入可互动物品的触发范围后显示，离开范围后自动关闭。

## 注意
README.md 的玩法文档可能由非工程人员书写，可能存在缺失实现细节等问题。如果发现描述不清或存在潜在歧义，必须在开发前先与用户确认，对齐需求后再进行开发。
每次开发/修改一个小功能后就 commit 一次，不要累积大量修改后再 commit，commit 文本要清晰描述本次修改的内容和目的。