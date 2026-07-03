# AI 项目经理助手 MVP 本地使用手册

## 适用范围

这套系统当前是本地单用户 MVP，适合在个人电脑上管理项目、任务、风险、信息归集、文档生成和 AI 助手问答。默认使用离线内置模型，不配置外部 API 也能试用核心流程。

## 一、首次安装

进入项目目录：

```bash
cd /Users/chenxiaoyong/Documents/个人/codex/ai-project-manager-mvp
```

安装后端依赖：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

安装前端依赖：

```bash
cd ../frontend
npm install
```

首次安装只需要做一次。后续日常使用直接运行启动脚本即可。

## 二、一键启动

```bash
cd /Users/chenxiaoyong/Documents/个人/codex/ai-project-manager-mvp
./scripts/start-local.sh
```

如果习惯从 Finder 操作，也可以双击桌面或项目目录里的 `启动 AI项目经理助手.command`。双击启动时会打开一个终端窗口，请保持窗口打开；关闭窗口或按 `Control+C` 会停止服务。桌面脚本已固定指向项目目录，即使放在桌面也不会去桌面查找 `backend/` 和 `frontend/`。

启动成功后访问：

```text
http://127.0.0.1:5173
```

后端健康检查地址：

```text
http://127.0.0.1:8000/health
```

命令行启动脚本会在后台启动前后端，并把运行信息写入：

```text
.runtime/backend.log
.runtime/frontend.log
.runtime/backend.pid
.runtime/frontend.pid
```

如果再次执行启动脚本，系统会提示服务已在运行，不会重复启动。

如果页面提示新接口 404，通常是旧后端进程还在运行。执行下面两行会关闭旧进程并启动最新版服务：

```bash
./scripts/stop-local.sh
./scripts/start-local.sh
```

如果页面出现 `API request failed: 500`，同时日志里有 `connect ECONNREFUSED 127.0.0.1:8000`，说明前端启动了但后端没有启动成功。请关闭服务后重新双击 `启动 AI项目经理助手.command`，新版双击脚本会检查后端健康状态，后端没起来时会直接显示失败日志。

## 三、一键关闭

```bash
cd /Users/chenxiaoyong/Documents/个人/codex/ai-project-manager-mvp
./scripts/stop-local.sh
```

如果习惯从 Finder 操作，也可以双击桌面或项目目录里的 `关闭 AI项目经理助手.command`。

只查看将要关闭哪些进程，不真正关闭：

```bash
./scripts/stop-local.sh --dry-run
```

## 四、使用者菜单

左侧导航底部显示当前系统使用者。点击用户名 `陈晓勇` 可以打开使用者菜单：

- `导出系统数据`：下载一个 zip 包，包含 SQLite 数据库、上传模板和 Word 导出文件。
- `清空系统数据`：清空项目、任务、风险、需求、里程碑、信息归集、待确认事项、文档模板、文档版本和聊天记录。清空前系统会自动生成备份 zip。

清空成功后会显示本次备份位置，并提供 `下载备份` 按钮。备份文件也会保留在：

```text
backend/data/backups/
```

清空数据后系统会保留模型配置，但业务数据会变为空。需要恢复演示数据时，可以执行：

```bash
python3 scripts/reset-demo-data.py --reset-demo --yes
```

## 五、端口被占用时

默认端口：

- 前端：`5173`
- 后端：`8000`

如果端口被占用，可以先关闭已有服务：

```bash
./scripts/stop-local.sh
```

也可以换端口启动：

```bash
BACKEND_PORT=8001 FRONTEND_PORT=5174 ./scripts/start-local.sh
```

换端口后访问：

```text
http://127.0.0.1:5174
```

## 六、数据存储位置

主数据库：

```text
backend/data/app.db
```

数据库备份：

```text
backend/data/backups/
```

上传的文档模板：

```text
storage/templates/
```

导出的 Word 文档：

```text
storage/exports/
```

数据库采用 SQLite。项目、任务、风险、需求、里程碑、信息归集、待确认事项、文档模板、文档版本、聊天记录和模型配置都保存在 `backend/data/app.db`。

## 七、核心使用流程

1. 打开 `项目驾驶舱`，选择或查看当前项目。
2. 在 `信息归集` 粘贴会议纪要、群聊记录或日报，提取待确认事项。
3. 在确认页编辑候选任务、风险、需求或里程碑，然后确认落库。
4. 在 `任务进度看板` 查看任务看板、列表、甘特和日历视图。
5. 在 `风险与成本` 维护风险状态和需求来源。
6. 在 `智能文档中心` 选择模板、录入内容、生成文档、预览并导出 Word。
7. 在右侧 `AI 项目助手` 询问当前项目风险、进度、周报或创建待确认任务。

## 八、模型配置

默认配置是 `离线内置模型`，可离线使用。

如需连接真实模型，在 `模型与 Agent` 页面选择对应预设并填写 API Key。当前内置：

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

本地 LM Studio 默认地址：

```text
http://localhost:1234/v1
```

本地 Ollama 默认地址：

```text
http://127.0.0.1:11434
```

保存配置后可以点击 `测试连通性`。

## 九、重置演示数据

预览将清理哪些测试数据：

```bash
python3 scripts/reset-demo-data.py --smoke-only
```

清理测试数据并自动备份数据库：

```bash
python3 scripts/reset-demo-data.py --smoke-only --yes
```

重建演示数据库：

```bash
python3 scripts/reset-demo-data.py --reset-demo --yes
```

## 十、验证系统是否正常

后端测试：

```bash
cd /Users/chenxiaoyong/Documents/个人/codex/ai-project-manager-mvp/backend
python3 -m pytest -q
```

前端构建：

```bash
cd /Users/chenxiaoyong/Documents/个人/codex/ai-project-manager-mvp/frontend
npm run build
```

浏览器核心链路 smoke：

```bash
cd /Users/chenxiaoyong/Documents/个人/codex/ai-project-manager-mvp
./scripts/run-smoke.sh
```

## 十一、常见问题

### 启动提示端口被占用

先执行：

```bash
./scripts/stop-local.sh
```

如果仍被占用，换端口启动：

```bash
BACKEND_PORT=8001 FRONTEND_PORT=5174 ./scripts/start-local.sh
```

### 前端打不开

查看前端日志：

```bash
tail -n 80 .runtime/frontend.log
```

### 后端接口不通

查看后端日志：

```bash
tail -n 80 .runtime/backend.log
```

也可以直接打开：

```text
http://127.0.0.1:8000/health
```

如果新增功能提示 `API request failed: 404`，先重启本地服务：

```bash
./scripts/stop-local.sh
./scripts/start-local.sh
```

### 模型连通性失败

先确认 API 地址、模型名和 API Key 是否正确。本地 LM Studio 或 Ollama 还需要先启动对应本地模型服务。

### 想恢复干净演示环境

执行：

```bash
python3 scripts/reset-demo-data.py --reset-demo --yes
```

该命令会重建本地 SQLite 数据库，执行前会备份当前数据库。
