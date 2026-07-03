# AI Project Manager MVP

本地可用的 AI 项目经理助手 MVP。当前已完成 P0-P7：项目管理、任务多视图、风险联动、信息归集确认落库、文档生成导出、默认模型配置、右侧 AI 项目助手、对话持久化、本地一键启动/关闭脚本和稳定化修复。

## Structure

```text
ai-project-manager-mvp/
  backend/          FastAPI + SQLite
  frontend/         Vue 3 + Vite + TypeScript + Element Plus
  docs/             本地使用手册
  scripts/          本地启动、关闭、重置和 smoke 脚本
  storage/
    templates/      上传的模板文件
    exports/        Word 导出文件
```

## User Manual

完整本地使用手册见：

```text
docs/user-manual.md
```

## Quick Start

首次运行先安装依赖：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd ../frontend
npm install
```

之后可一键启动前后端。脚本会后台启动服务，并写入 `.runtime/*.pid` 和 `.runtime/*.log`：

```bash
cd ..
./scripts/start-local.sh
```

默认地址：

```text
Frontend: http://127.0.0.1:5173
Backend:  http://127.0.0.1:8000/health
```

关闭服务：

```bash
./scripts/stop-local.sh
```

如果 8000 或 5173 被占用，可以先停止旧进程，或临时换端口：

```bash
BACKEND_PORT=8001 FRONTEND_PORT=5174 ./scripts/start-local.sh
```

## Manual Start

后端：

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm run dev
```

## Current P6 Scope

- Project CRUD, project dashboard flag, and project summary metrics.
- Task create, status update, list, lightweight Gantt, and calendar view.
- Risk list, risk status update, risk summary, demand count, budget usage, and health score.
- Snippet ingest, structured extraction candidates, edit, dismiss, and confirm-to-database workflow.
- Document template upload, draft generation, HTML preview, version history, and Word export.
- Document center supports common software delivery document types and extra user input for each generation.
- Default model configuration, API Key masked response, model connectivity test, and capability-level override placeholders.
- Collapsible assistant panel, context-aware Q&A, chat history persistence, and task-creation prompts routed into pending confirmations.
- Task list pagination and demand source labels in risk/cost view.
- Local start script and basic testing checklist.

## Local Test Checklist

1. 打开项目驾驶舱，确认项目卡片正常，右上角无版本标识；点击右侧 AI 面板按钮可收起/展开。
2. 在任务进度看板新建任务，确认看板、列表、甘特和日历同步出现；列表视图每页展示 10 条。
3. 在风险与成本页切换项目并关闭一个风险，确认指标刷新；新增需求卡片显示信息来源。
4. 在信息归集页粘贴会议纪要，提取候选项，编辑后确认落库。
5. 在智能文档中心选择软件交付文档类型，上传 Markdown 模板，输入本次新增内容，生成草稿并导出 Word。
6. 在模型与 Agent 页保存默认模型，点击测试连通性。
7. 在右侧 AI 助手提问“这个项目现在最大风险是什么？”。
8. 在右侧 AI 助手输入“创建一个接口文档任务”，再到信息归集页确认出现待确认任务。

## Optional AI Extraction Provider

默认使用 deterministic 本地规则抽取器，离线可测。
如需试真实模型，启动后端前设置环境变量：

```bash
export AI_EXTRACTOR_PROVIDER=openai-compatible
export AI_BASE_URL=https://api.example.com/v1
export AI_API_KEY=your-key
export AI_MODEL=qwen-plus
```

Ollama：

```bash
export AI_EXTRACTOR_PROVIDER=ollama
export AI_BASE_URL=http://127.0.0.1:11434
export AI_MODEL=qwen2.5:14b
```

模型与 Agent 页面保存的 API Key 不会明文返回到前端；再次读取时会显示为 `********`。

## Model Presets

模型与 Agent 页面已内置以下配置预设：

- 离线内置模型
- OpenAI Compatible
- 阿里百炼 / 通义千问
- DeepSeek
- Kimi / Moonshot
- 智谱 GLM
- 火山方舟 / 豆包
- 百度千帆
- 腾讯混元
- 硅基流动
- 本地 LM Studio
- 本地 Ollama

国内模型预设都按 OpenAI-compatible 接口处理；如果厂商账号、地域、模型名或网关地址不同，可在页面里继续手工覆盖 `模型名称`、`API 地址 / 本地地址` 和 `API Key`。

## Verification

```bash
cd backend && python3 -m pytest -q
cd frontend && npm run build
```

Run the browser smoke flow after both services are running:

```bash
./scripts/run-smoke.sh
```

## Demo Data Reset

Smoke tests and local demos can leave temporary tasks, risks, demands, document versions, templates, chat messages, and exported files. Preview cleanup first:

```bash
python3 scripts/reset-demo-data.py --smoke-only
```

Apply cleanup with a database backup:

```bash
python3 scripts/reset-demo-data.py --smoke-only --yes
```

Recreate the local SQLite database from bundled seed data:

```bash
python3 scripts/reset-demo-data.py --reset-demo --yes
```

## Known Limits

- PDF 导出和飞书云文档同步目前只是状态字段，未接真实同步。
- 上传的模板第一期作为模板资产和生成类型使用，暂不继承 `.docx` 原始样式。
- 右侧助手目前使用本地项目上下文规则回答；真实模型问答可在后续接入统一模型配置。
- 当前版本面向单用户本地使用，未实现多用户权限、审计和组织协作。
