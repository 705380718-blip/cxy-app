# 交付小助手 0.5.7

## Mac 接收方版本（2026-11-09）

新增 Apple Silicon Mac 分发工具与微信 4.1.15（270115）候选适配。该构建须通过接收方本机密钥、数据库解密完整性及消息结构检查，尚未完成目标版本实机验收。当前自动采集仅匹配群聊，不支持填写个人昵称监测私聊。

- [接收方使用手册](packaging/mac-recipient/manual.html) / [PDF](packaging/mac-recipient/manual.pdf)
- [版本说明](packaging/mac-recipient/release-notes.md)
- [源码运行与打包](source-setup.md)
- 回归测试：332 项通过，1 项 Windows 原生 ACL 条件跳过。测试使用构造数据，不要求真实微信或模型密钥。


剩余离线开发已完成；本机 Mac 微信 4.1.13（269629）指定测试群的历史读取、新消息与 @昵称识别、重启去重也已验证。0.5.2 修复增量读取；0.5.3 已完成紧凑分析工作台；0.5.4 支持已确认事项撤回与恢复，任务提取要求明确行动原文并校验请求/承诺语境。0.5.5 新增待复核建议多选、跨页选择与批量采纳/忽略；0.5.6 支持自动整理新消息，0.5.7 删除“更多”菜单并统一工作台视觉规范。详见 [使用说明](./delivery-guide.md) 与 [案例事实和演示稿](./case-notes.md)。本机已有用户完成的一批分析；独立质量评测与岗位收益试用仍待补充；后文 Windows 解码工作不表示已取得目标真机验证。

# 微信群聊问题整理工具：本地监听 POC

这是一个 macOS/Windows 共用业务核心的本地原型：从指定微信群的本机数据库副本读取消息，按规则提取问题，提供人工确认/忽略和时间段报告。Web 服务只绑定 `127.0.0.1:8791`，不控制微信 UI、不发送消息、不写微信原数据库，原采集链路不调用云端模型；新增的 DeepSeek 构造样例测试由用户主动点击后调用云端 API。

## 2026-10-10：交付小助手开发版

已完成 T0–T8 的离线工程链路及五步交互流程：导入、模型配置、持久分析队列、事项复核、报告评测与分发。本机用户已配置模型并完成一批分析；本轮界面验收使用构造接口，未新增云端请求。默认 AI 与来源自动分析均关闭。

启动独立开发版（复用已安装的 `.venv`）：

```bash
./start-delivery-dev.sh
```

默认开发地址为 `http://127.0.0.1:8792/`，独立数据库为 `~/Library/Application Support/交付小助手-dev/data/delivery.db`。原工具工作库不受影响。默认关闭微信解码并使用空的微信数据目录；若端口已占用，入口直接失败，不结束其他进程。可以通过 `WML_PORT`、`WML_DATABASE_PATH` 或 `WML_ENV_FILE` 指定另一份配置。

使用步骤：

1. “微信与群聊”：选择或新建整理空间，输入群完整名称和自己的昵称，选择采集或导入。一次保存自动完成白名单与来源绑定。
2. “采集规则”：设置关键词、关注人员、@我规则和消息保留窗口，保存后进入采集。
3. “开始采集”：微信具备解析条件时启动；无法解析可切换手动导入，预览 TXT/CSV 后确认。页面显示当前空间最近消息。
4. “AI 分析”：通过右上角“设置”配置模型、启用分析；侧栏分页预览当前来源的脱敏文本，确认后入队，按每页 5 条筛选建议并打开复核侧栏。消息 ID、自动分析和手动事项位于折叠选项。
5. “信息与报告”：查看与跟进事项，展开报告入口，按日期生成并导出。辅助评测与旧规则汇总已移出界面。

完整步骤与构造文本示例见 `delivery-guide.md`。本机微信使用客户端登录态，不在本工具输入微信密码；当前未验证构建仍会阻断解码。空间切换同步到导入、分析和报告，旧消息不会自动搬移。

数据库迁移前自动使用 SQLite backup API 备份已有旧库，路径为数据库同级的 `backups/`；迁移失败会回滚。恢复时先停止服务，将失败库及对应 WAL/SHM 移到隔离目录，再用备份恢复；不要在运行中覆盖数据库。备份是私有历史副本，当前不自动清理备份，生产使用前须落实备份留存策略。

DeepSeek 私有配置位于数据库同级的 `private/deepseek-config.json`；macOS 目录权限 `0700`、文件 `0600`，Windows 代码使用当前用户 DPAPI/ACL（本次未做 Windows 真机验证）。开发也支持 `DEEPSEEK_API_KEY` 环境变量；清除本机文件中的 Key 不会移除进程环境中的 Key。GET 设置、校验错误及导出不回显密钥，浏览器不写 localStorage。地址限定 DeepSeek 官方 HTTPS 主机，不跟随携带鉴权的重定向。

请求超时最大 60 秒，连通测试总上限 210 秒；模型列表与补全各最多 3 次，JSON 结果错误最多纠正 1 次；所有请求及重试计入每天预算。预算与参数为配置初值，不是实测性能指标。

“AI 分析”先选来源及可选消息范围，预览实际脱敏正文/引用/未关闭事项，再勾选同意发送并入队。预览不需要 Key；入队要求启用 AI 且有 Key，配置或事项变化需重新预览。每批最多 80 条新消息，可在设置页调低；超长上下文自动缩小批次，剩余消息用“预览下一批”继续，单条超长不会静默跳过。

模型结果只创建待复核建议。查看原文后可采纳为新事项，或人工关联同来源事项；后续进展需采纳，版本变化返回 409。事项支持人工改标题、责任人、期限和进展，复核状态/业务状态独立，人工确认业务完成才关闭；同来源合并保留依据与来源链。

按来源启用后续自动分析需要单独同意，从启用时最后消息 ID 之后开始；晚到历史消息也按新本地 ID 排队。关闭全局 AI 会暂停排队任务，关闭来源自动分析会停止新增自动任务；已排队/运行任务可单独取消。单进程 worker 每 2 秒检查，固定输入/模型/提示词/事项版本并持久保存，短事务不等待网络。活动运行总上限 210 秒、每任务最多 3 次尝试（含中断或预算阻断），手动重试只使用剩余次数；格式错误最多纠正一次。取消或留存清理后不会采纳迟到结果。

事项 API 支持双状态、同来源证据与版本冲突 409；消息清理会失效关联的派生事项正文，移除受影响任务/建议和报告/评测缓存。当前采用保守整项失效，字段级保留将在后续优化；导出文件和迁移备份不自动跨目录删除。

验证命令：

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python -m compileall -q app scripts tools tests
node --check app/static/app.js
node --check app/static/delivery.js
node --check app/static/workbench.js
bash -n start-delivery-dev.sh
```

2026-10-10 第二日阶段：131 passed，1 条原有 Starlette/httpx 弃用警告；最终离线验收：171 passed（同一条原有警告），干净目录安装/启动/导入/报告/评测通过。真实 DeepSeek API 未调用。浏览器验证了手动事项、双状态、原文、模拟建议采纳、后续进展关联和人工关闭；1280/760 布局无横向溢出。

可重现完整离线 UI 流程（单独临时数据库 + HTTP MockTransport，不调用云端）：

```bash
.venv/bin/python scripts/serve-offline-delivery-demo.py --port 8793
```

项目为“构造样例-离线接口模拟”、模型 ID 为 `mock-delivery-fixture`。按范围预览→入队→等待 2 秒→刷新→采纳建议→人工跟进。停止服务会清理临时数据库；请勿放入真实消息或真实 Key。临时页只是操作验收，不代表 DeepSeek 分析质量。常用入口仍是 `start-delivery-dev.sh` / 8792。

## 当前交付状态

- macOS 链路保留原有实测能力和回归测试。
- Windows 的程序发现、账号选择、DB/WAL/SHM 变化观察、整组稳定快照、WAL checksum/提交边界、HMAC 页认证框架、DPAPI 密钥仓库、精确 profile/schema 门禁、监听器、诊断、UI 和四个交付命令已经实现。
- 当前仓库没有目标 Windows 微信的真实版本、密钥参数和 schema 样本，所以默认 profile 是禁用模板。Windows 第一次运行会进入安全的“观察模式”，不会把未验证版本伪装成成功解码。
- 工具不包含通用进程内存扫描器。首次密钥准备接受由“该微信构建专用、用户主动运行且经过审计”的 provider 导出的临时候选 JSON，并在 DPAPI 入库前逐库验证 HMAC、`quick_check` 和 schema。

## Windows 第一次验证

推荐先直接复制源码目录到 Windows 测试机；若已构建带 runtime 的 ZIP，则不需要安装 Python。

1. 登录自有测试微信账号，进入已告知的测试群。
2. 双击 `packaging/windows/1-首次密钥准备.cmd`。
3. 脚本会先在桌面生成 `wechat-windows-diagnostic.json`。该文件不含密钥、账号名和聊天正文。
4. 把诊断文件带回开发环境，用它固定 `exe version + build + layout fingerprint` 并完成目标构建的 crypto/schema profile。
5. 准备好已审计 provider 导出的候选密钥 JSON 后，再次运行第 2 步，输入 `PREPARE`、profile ID 和候选文件路径。
6. 只有候选密钥逐库通过 HMAC、解密快照 `quick_check=ok`、关键表和 schema 指纹检查后，工具才会写入当前 Windows 用户绑定的 DPAPI 密钥仓库。
7. 双击 `packaging/windows/2-启动服务.cmd`，打开 `http://127.0.0.1:8791/`，配置精确群名后启动监听。

完整真机验收表见 [WINDOWS-VALIDATION.md](./WINDOWS-VALIDATION.md)。

## Windows 候选密钥格式

候选文件只作为一次性输入，工具不会复制它。不要把该文件放入仓库、云盘或聊天工具。

```json
{
  "keys": {
    "db_storage/contact/contact.db": {
      "encryption_key": "{{64位十六进制 AES-256 原始密钥}}",
      "hmac_key": "{{可选：64位十六进制 HMAC key；标准 SQLCipher 4 profile 会自动派生}}"
    },
    "db_storage/message/message_0.db": {
      "encryption_key": "{{64位十六进制 AES-256 原始密钥}}",
      "hmac_key": "{{可选：64位十六进制 HMAC key；标准 SQLCipher 4 profile 会自动派生}}"
    }
  }
}
```

密钥准备有两个开发阶段：

```powershell
# profile 已固定版本、build、layout 和 HMAC 参数，但尚未写 schema 指纹时：
python tools/windows_key_prep.py inspect-candidates `
  --profile-id {{profile-id}} --candidates {{candidate-json}}

# schema 指纹审核后启用 profile，正式验证并写入 DPAPI：
python tools/windows_key_prep.py prepare `
  --profile-id {{profile-id}} --candidates {{candidate-json}}
```

Windows DPAPI 默认绑定“同一台计算机上的同一登录用户”；它不能防御同一用户会话内已经获得执行权限的恶意程序。因此 private 目录还会移除继承 ACL，只授权当前用户。

## Windows 解码 profile

配置文件位于 `config/windows-decoder-profiles.json`。`enabled: true` 的 profile 必须同时固定：

- 微信 PE file version；
- build；
- 归一化数据布局指纹；
- HMAC-SHA512 页认证参数；
- 解密后 schema 指纹；
- 联系人、成员和消息字段映射。

Windows 不读取 `WML_ALLOW_UNVERIFIED_DECODER` 绕过项。版本、build、布局、账号、密钥 profile、schema 任一不匹配，都只能观察文件变化，不能向业务库摄入消息。

## Windows 日常入口

- `1-首次密钥准备.cmd`：生成脱敏诊断；在 profile 与候选密钥已准备时执行验证和 DPAPI 封装。
- `2-启动服务.cmd`：只在固定本机 URL 启动本产品并写入专用 PID 记录。
- `3-停止服务.cmd`：校验 PID 命令行属于本项目后才停止，不会宽泛结束所有 Python。
- `4-清除本工具数据.cmd`：二次确认后只删除 `%LOCALAPPDATA%\GroupChatOrganizer`，包含业务库、DPAPI blob、明文快照、配置、日志和 PID；不会触碰微信目录。

## 构建无 Python 依赖的 Windows ZIP

在 Windows 构建机准备官方 Python 3.12 x64 embeddable ZIP，校验其官方 SHA256，再运行：

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/build-windows-package.ps1 `
  -PythonEmbeddableZip C:\build\python-3.12.10-embed-amd64.zip `
  -PythonZipSha256 {{从官方发布页独立核验的 SHA256}} `
  -Wheelhouse C:\build\wheelhouse
```

构建脚本不会跳过哈希检查。使用 `-Wheelhouse` 时依赖安装离线完成；未提供时构建机需要访问 Python 包源。最终 ZIP 位于 `dist/windows/group-chat-organizer-windows.zip`，四个编号命令位于 ZIP 根目录。

## macOS 启动与已验证范围

```bash
cd <项目目录>
chmod +x start-mac.sh
./start-mac.sh
```

macOS 原链路已在微信 `4.1.11.55` 和升级后的 `4.1.12 (269341)` 上做过本机实验，包括指定群历史读取和编号增量。macOS 仍使用原有“最大已验证版本”门禁；Windows 使用更严格的 exact profile 门禁，两者不能混用。

## 业务功能

- 精确群名白名单与多群监听；
- 默认最近 7 天历史和留存，按群记录首次导入；
- `@我`、`@指定人员`、问题表达和自定义关键词；
- 文本、引用消息结构化展示，图片和未知类型使用占位；
- 本地 SQLite 去重、检索、分页、批量确认/忽略；
- 本地时间段 Markdown 报告；
- 状态栏显示平台、版本/build、账号选择、DB/WAL/SHM、profile、密钥验证、schema、最近变化/解码和中文阻断原因。

## 本机开发测试

```bash
cd <项目目录>
.venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python -m compileall app scripts tools tests
```

macOS 测试能验证平台中立业务逻辑、Windows 发现/门禁、稳定快照、WAL 校验、HMAC fixture、schema、fake protector 密钥仓库与 API；不能替代真实 Windows DPAPI/ACL、Defender/EDR、微信进程、版本资源和消息对账。

## 隐私与边界

- 原微信 DB/WAL/SHM 只按文件读取并复制，从不以 SQLite 打开原库，也不执行 checkpoint。
- 开发版与 Windows 试运行包的数据位于独立用户应用目录；旧 macOS 离线 ZIP 数据位于解压目录的 `runtime/`，均与原工具工作库隔离。
- API 不返回密钥、解码命令、完整账号路径或原始传输 XML。
- 诊断只包含相对数据库路径和截断指纹，不包含账号名和聊天正文。
- 这是非微信官方兼容原型。组织部署优先评估企业微信官方会话内容存档，并遵循组织安全策略；如果 EDR 阻断密钥 provider，不应尝试绕过。


## 0.5.5 分发验收

```bash
.venv/bin/python scripts/build-delivery-package.py
.venv/bin/python scripts/verify-delivery-package.py dist/wechat-delivery-offline-0.5.5-macos-arm64.zip
node --check app/static/followup-reports.js
```

ZIP 包含 macOS arm64 / CPython 3.11 的依赖 wheels，需本机安装 Python 3.11；不包含解释器、密钥、真实消息、数据库或迁移备份。构造样例文件标明数据来源。用时/正确性由参与者记录；分发验收使用构造资料，未调用真实模型。

## Windows 0.5.7 本机实施包（2026-10-12）

已增加 Windows 用户态启停与托盘、一次性本机登录、当前用户独占 ACL、锁定 Python 3.14.8 x64 离线运行时及依赖、完整性校验、旧版只读导出、一键构造自检。详见 [试运行与真机验收说明](packaging/windows/windows-guide.md)。

本机共享测试通过不代表 Windows 真机验收。当前微信 decoder profile 仍为禁用模板；可先使用导入流程。真实 Windows 权限/浏览器/托盘、微信精确版本与密钥提供器、模型质量、24 小时稳定性及签名须在目标环境完成。不要覆盖旧业务库或直接启用未验证模板。
