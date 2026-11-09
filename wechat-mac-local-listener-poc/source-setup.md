# 源码运行与 Mac 打包

## 本地运行

Python 3.11；进入本项目目录后执行：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt -r requirements.txt
bash start-delivery-dev.sh
```

默认使用独立的导入模式。按终端提示打开本机地址；模型功能需在界面自行配置，源码不附带任何 API 密钥或聊天数据。所有端口及数据位置以环境配置为准。不要使用保留端口 5173 / 8000。

## 测试

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider
```

接收方工具测试在 macOS 上执行；部分测试依赖 macOS 系统组件。Windows 原生 ACL 测试需在 Windows 上运行。

## 构建 Apple Silicon 接收方包

在 Apple Silicon Mac 上准备独立、干净的 CPython 3.11.15 arm64 运行时；打包器适配 uv 管理的该版本目录结构，运行时路径通过参数传入。系统需提供 install_name_tool 和 codesign。先缓存依赖，再构建；产物不写入 Git。

```bash
mkdir -p dist/wheelhouse dist/mac-recipient-wheels
.venv/bin/python -m pip download --only-binary=:all: -r requirements-lock.txt -d dist/wheelhouse
.venv/bin/python -m pip download --only-binary=:all: -r packaging/mac-recipient/requirements-setup.txt -d dist/mac-recipient-wheels
python3 scripts/build-mac-recipient.py --runtime "${CLEAN_PYTHON_RUNTIME}"
python3 scripts/verify-mac-recipient.py dist/mac-recipient-20261109/wechat-delivery-mac-0.5.7-recipient-20261109-wx415-arm64.zip
.venv/bin/python scripts/verify-wx415-candidate.py dist/mac-recipient-20261109/wechat-delivery-mac-0.5.7-recipient-20261109-wx415-arm64.zip
```

`CLEAN_PYTHON_RUNTIME` 应指向干净运行时根目录，其中应有 bin/python3.11 和 lib/python3.11。原生隔离测试需可用的 macOS C 编译器。新源码检出首次运行验收前创建 output/mac-recipient-20261109 目录；一般包验收脚本也会创建它。

Mac 包采用本地 ad-hoc 签名，未完成 Apple Developer ID 签名或公证。构造数据库验收不代表目标微信版本的真实密钥准备、持续采集或其他 macOS 版本均已兼容。
