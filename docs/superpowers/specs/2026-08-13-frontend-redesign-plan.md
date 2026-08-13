# PRD Stress Test 前端重构实现计划

> 依据 `docs/superpowers/specs/2026-08-13-frontend-redesign-design.md`，8 天里程碑拆解为可执行任务。每项完成即测试。

## D1 — FastAPI 骨架（api/）

1. `api/app.py` — FastAPI 实例、CORS、静态托管 `web/dist`、`GET /api/meta`
2. `api/deps.py` — LLM 工厂、store 单例、rate_limit 包装
3. `api/routes_review.py` — `POST /api/reviews`（扣额度 + 后台管线 + run 注册表）、`GET .../stream`（SSE 两段式）、`GET .../{id}`、`POST .../discuss`（SSE 追问）
4. `api/routes_skills.py` — skills 列表/SKILL.md/反馈/停用/置顶/提炼/提案
5. `api/routes_history.py` — 历史列表/详情
6. `api/routes_ablation.py` — 报告/后台重跑/状态轮询
7. `POST /api/uploads` — prd_loader 包装
8. 测试 `tests/test_api.py` — SSE 事件顺序、429、上传边界、审批流（注入 MockProvider）
9. 依赖：pyproject/requirements 增加 fastapi、uvicorn、python-multipart

## D2~3 — 前端地基（web/）

1. Vite + React + TS 脚手架（`npm create vite`）
2. 自托管字体（Pixelify Sans + Inter woff2；下载失败则系统字体回退）
3. `tokens.css` — 全部设计 token（色板/字体/形状/动效）
4. 13 件组件库（先静态、无数据依赖）
5. 评审工作台静态版（composer/进度/裁决/卡片骨架）— 路由 + 三页骨架

## D4 — 流式全链路

1. `lib/api.ts` + `lib/useSSE.ts`（解析器/重连/error 事件）
2. composer 提交 → SSE → 阶段进度 → 推理终端 → 裁决三列 → Critic 卡片
3. 追问对话（discuss SSE）
4. Vitest：SSE 解析器 + token 冒烟 + CritiqueCard

## D5 — 历史 + Skill 库

1. HistoryRail 列表 + 详情恢复
2. Skill 库双栏 + SKILL.md + 反馈按钮

## D6 — 提炼 + 消融 + 上传

1. 提案卡片（采纳/驳回/编辑/证据）
2. 消融页（指标卡/对比表/像素柱状图/重跑轮询）
3. 上传解析接入 composer

## D7 — 部署

1. Dockerfile 多阶段 + docker-compose.yml
2. 本地 compose 验证全流程
3. HF Docker Space 配置 + README 更新（截图/架构/新栈说明）

## D8 — 打磨

1. 动效细节（按钮键程、光标闪烁、P0 入场）
2. 空态/响应式/断线重连横幅
3. 验收清单全过（golden PRD 全流程）
