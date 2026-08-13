# PRD Stress Test 前端重构设计：Codex × 8-bit

- 日期：2026-08-13
- 状态：已确认（用户口头确认三节设计后落盘）
- 关联：`README.md`、`src/ui/streamlit_app.py`（现役 UI）、`src/main.py`（管线入口）

## 1. 背景与目标

现役 UI 是 Streamlit（`src/ui/`），功能完整但"框架感"重。本次重构目标：

1. **现代化交互**：Codex 式体验——暗色、留白、渐进流式反馈、舒适阅读；
2. **差异化品牌**：8-bit 复古视觉（像素字体、硬边卡片、硬阴影），做到"一看就知道是这个产品"；
3. **简历叙事**：技术栈升级为主流生产栈（FastAPI + React + Docker），为 PM 岗求职提供完整产品案例；
4. **零风险迁移**：`src/` AI 管线一行不改，现有 102 个测试原样通过。

## 2. 已确认的关键决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 改造深度 | 前端完全重写（放弃 Streamlit 做 UI） | 简历信号最强；Streamlit 布局无法实现 Codex 式体验 |
| 技术栈 | FastAPI + React 19 (Vite + TS) | 用户熟 React；主流生产栈 |
| 视觉方向 | 「像素工作室 Pixel Studio」 | 4 方向对比后用户选定 |
| 品牌主色 | 品红 `#ff5fc8` | 差异化识别度；刻意避开 P0/P1/P2 语义色 |
| 像素浓度 | 标准 Standard | 标题/按钮/徽章像素字 + 硬边卡片；正文保持可读 |
| 功能范围 | 全功能移植（评审/历史/Skill 库/提炼/消融） | 用户明确要求 |
| 部署 | Docker 多阶段 + HF Docker Space | 线上 demo 链接继续有效；简历有 Docker 信号 |

## 3. 架构总览

```
web/                    前端（React 19 + Vite + TS）
├─ src/components/      13 件像素组件库
├─ src/pages/           评审工作台 / Skill 库 / 消融实验
├─ src/lib/api.ts       fetch 封装 + SSE 解析器
├─ src/lib/useSSE.ts    SSE hook（重连、错误事件）
├─ src/styles/tokens.css ★ 8-bit 设计 token
└─ public/fonts/        自托管 woff2（Pixelify Sans + Inter）
api/                    后端（FastAPI）
├─ app.py               入口 + 托管 web/dist 静态产物（单源部署）
├─ routes_review.py     评审 / SSE 流 / 追问 / 上传
├─ routes_skills.py     Skill 库 / 反馈 / 提炼 / 提案审批
├─ routes_history.py    历史 / 消融实验
└─ deps.py              复用 src/ 的 store、rate_limit、LLM 工厂
src/                    ★ 完全不动（102 测试原样通过）
app.py                  ★ 保留（Streamlit 遗留入口，回滚保险）
Dockerfile              多阶段：node build → python+uvicorn
docker-compose.yml      本地一键跑
```

### API 一览

| 端点 | 说明 |
|---|---|
| `GET /api/meta` | 模型/供应商/demo 配额状态（顶栏显示） |
| `POST /api/reviews` | 提交 PRD，扣额度，启动后台管线，返回 `run_id` |
| `GET /api/reviews/{run_id}/stream` | SSE 流：阶段/批评/互辩/思考/裁决事件 |
| `GET /api/reviews/{run_id}` | 取已完成 run 的完整结果（断线恢复用） |
| `POST /api/reviews/{run_id}/discuss` | 追问 Critic，响应为 SSE 流（复用 `run_critique_dialog`） |
| `POST /api/uploads` | PDF/Word/MD 解析（复用 `prd_loader.py`，2MB 上限） |
| `GET /api/history?n=20` · `GET /api/history/{run_id}` | 历史评审 |
| `GET /api/skills` · `GET /api/skills/{name}/md` | Skill 库（in-process `SkillRetriever`） |
| `POST /api/skills/{name}/feedback` | ✓采纳 / ✗误报（复用 `SkillCurator`） |
| `POST /api/skills/{name}/deprecate` · `/pin` | 停用 / 置顶 |
| `POST /api/distill` · `GET /api/proposals` | 提炼 + 待审提案列表 |
| `POST /api/proposals/{id}/approve` · `/reject` · `/save-edit` | 提案审批 |
| `GET /api/ablation` · `POST /api/ablation/run` · `GET /api/ablation/status` | 消融报告 / 后台重跑 / 轮询 |

### SSE 事件协议（`GET /api/reviews/{run_id}/stream`）

沿用 Streamlit 版验证过的**两段式**：graph 跑到 merge 节点后，把 critic 结果立刻推给前端，supervisor 单独流式。事件顺序：

```
phase {name:"intake"}
phase {name:"critics"}
critiques {critiques:[...]}          ← merge 节点产物，先到先看
phase {name:"challenges"}
challenges {challenges:[...], rounds, converged}
phase {name:"supervisor"}
thinking {delta:"..."}              ← 逐字流
verdict {verdict:{...}}             ← 结构化裁决
done {run_id, verdict}              ← 已持久化到 HistoryStore
error {message, retryable}          ← 任何异常（LLM 异常含 fallback 语义）
```

前端在 `critiques` 事件到达时立刻渲染 4 个 Critic 的 finding（消除 30 秒干等），随后裁决流式出现——Codex 式渐进反馈。

### 关键实现决策

- **两段式管线复用**：`run_pipeline(include_supervisor=False)` → 推 `critiques`/`challenges` → `run_supervisor_stream()` 逐 delta 转 `thinking` 事件 → `persist_run()` 落盘 → `done`。
- **run 注册表**：内存 `dict[run_id, asyncio.Queue]`；SSE 端点消费队列，断线重连后未消费事件不丢（队列保留至 `done` 后 1 小时或消费完成）。刷新页面 → 从 `/api/history` 恢复已完成 run。
- **Skill 显示层走 in-process**：不迁移 MCP 显示链路；MCP server 保留给外部消费者（README 的分层决策不变）。
- **字体自托管**：不依赖 Google Fonts CDN（大陆访问会被墙），woff2 进仓库。

## 4. 前端设计

### 信息架构（Codex 式骨架）

- **顶栏**：像素 Logo「PIXEL·PRD」+ 导航（评审 / 消融实验 / Skill 库）+ 右侧模型与 demo 配额状态
- **评审页**：左轨历史列表（Codex 会话列表式，含 P0/P1/P2 计数）；主面板 = composer → 阶段进度 → 推理终端 → 裁决三列 → 4 个 Critic 的 finding 卡片（含 ✓采纳/✗误报/追问）
- **Skill 库页**：左列表（使用次数/置顶/停用）+ 右 SKILL.md 详情；页内「提炼」区 = 提案卡片（采纳/驳回/编辑/证据）
- **消融页**：4 个 headline 指标卡 + 对比表 + 像素柱状图 + 重跑按钮 + 进度轮询

### 8-bit 设计 token（品红 × 标准浓度）

| Token | 值 |
|---|---|
| 主色 / hover | `#ff5fc8` / `#ff7fd4` |
| 画布 / 面板 / 边框 | `#0d0d0f` / `#16161a` / `#2e2e34`（1.5~2px 实线） |
| 文本 / 弱化 | `#e8e8ea` / `#9b9ba3` |
| 语义色 | P0 `#ff6b5e` · P1 `#ffc94d` · P2 `#6ea8ff` · 成功 `#8bff5f`（沿用现役语义，不参与品牌） |
| 显示字体 | Pixelify Sans（标题/按钮/徽章/Logo） |
| 正文字体 | Inter（正文/阅读区） |
| 代码字体 | 系统 mono（claim_id、证据行号、SKILL.md） |
| 形状 | 0 圆角 · 硬阴影 `3px 3px 0 #000`（无模糊） |
| 动效 | 按钮按下 = 位移 + 阴影塌缩 · 流式光标 `▌` 闪烁 · 进度 = 像素块填充 · `prefers-reduced-motion` 全关 |

### 8-bit 戏份分配（克制原则）

1. **只在等待时表演**：评审运行中——阶段像素进度条 + 推理终端闪烁光标，这是 8-bit 的灵魂时刻；
2. **静态页面不表演**：Skill 库/消融只有字体与硬边卡片，无扫描线、无跑马灯；
3. **微交互**：按钮"键程感"、P0 卡片入场 2 帧位移——细节复古，全局保持 Codex 的安静。

### 组件清单（web/src/components/）

`TopBar · PixelButton · SeverityBadge · CritiqueCard · VerdictPanel · ThinkingTerminal · Composer · HistoryRail · SkillCard · ProposalCard · MetricCard · PixelProgress · EmptyState`

### 状态管理与路由

- 路由：`react-router-dom`（3 个视图 + 历史详情）
- 状态：自定义 hooks + context（`useSSE` 管理流式状态）；不引入全局状态库——run 是短暂的，没有跨页共享状态值得为之引入依赖
- 样式：CSS 变量 token 层 + CSS Modules，不引 UI 库（自建设计系统正是卖点）；消融柱状图手写 CSS 像素条，零图表依赖

## 5. 错误处理

- SSE 任何异常 → `error` 事件（带 `retryable`），流内报错不中断页面；连接断开 → 3 秒重连 + 「📡 信号丢失 · 重连中」像素横幅
- 速率限制：API 中间件复刻 `rate_limit.py` 语义（429 + 剩余额度响应头）；前端顶栏显示 demo 配额条
- 上传失败分类提示（过大/类型不支持/解析为空）——复用 `prd_loader.py` 异常类型
- LLM 层已有 stream→complete 降级（`src/` 不动），API 只负责包装成 error 事件；MockProvider 本地兜底保留
- 全局：错误 toast + 空态 + 重试按钮；SSE 解析器独立成模块（易测）

## 6. 测试策略

- **后端**：FastAPI TestClient + 注入 MockProvider，新增约 15 个路由测试——SSE 事件顺序、429、上传边界、提案审批流。`src/` 不动 → 现有 102 测试原样通过
- **前端**：Vitest——SSE 解析器（流切分/半条事件边界，最易出错）、token 冒烟、CritiqueCard 严重度渲染
- **验收清单**：内置 golden PRD 走全流程：输入 → 4 critic → 互辩 → 流式裁决 → 追问 → 历史 → 反馈 → 提炼 → 消融

## 7. 里程碑（8 天）

| 天 | 交付 |
|---|---|
| D1 | FastAPI 骨架 + `/api/reviews` SSE 两段式流 + 路由测试 |
| D2~3 | Vite+TS 脚手架 + tokens.css + 13 件组件库 + 工作台静态版 |
| D4 | 流式全链路：composer → SSE → 推理终端 → 裁决卡片 → 追问 |
| D5 | 历史 + Skill 库 + ✓/✗ 反馈 |
| D6 | 提炼审批 + 消融页 + 上传解析 |
| D7 | Docker 多阶段 + compose + HF Space 切换上线 + README |
| D8 | 打磨：动效、空态、响应式、验收清单全过 |

**滑期裁剪顺序**（如 8 天不够，按序砍）：消融图表 → 置顶/停用 → 上传解析 → 追问。核心评审流永不砍。

## 8. 面试叙事素材（边做边记录）

1. **「为什么品红」**——差异化识别度 + 刻意避开 P0/P1/P2 语义色，品牌色与数据色不抢戏
2. **「为什么标准浓度」**——PM 用户连续读几十条 finding，舒适度 > 复古浓度；8-bit 只"在等待时表演"
3. **「为什么两段式流式」**——30 秒评审的等待心理：先看 finding 再看裁决，Codex 式渐进反馈
4. **数据闭环**——消融页重演现有数据（precision +100%、noise -55%），新旧 UI 结论一致

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| HF Docker Space 冷启动/超时 | 本地 compose 为默认体验；demo 页做首次加载提示 |
| 8-bit 美学伤害可读性 | 标准浓度 + 自托管可读字体 + reduced-motion |
| 全功能移植 8 天偏紧 | 滑期裁剪顺序已定（见 §7） |
| SSE 在 HF 代理层被缓冲 | 已在 Streamlit 版验证流式可行；必要时加心跳注释事件 |

## 10. 非目标（v1 明确不做）

- 明暗主题切换（8-bit 即暗色）
- 音效（浏览器 autoplay 政策 + 阅读场景干扰）
- 重写/升级 AI 管线或换 LLM
- 多租户、账号系统
- MCP 显示层迁移（保留给外部消费者）
