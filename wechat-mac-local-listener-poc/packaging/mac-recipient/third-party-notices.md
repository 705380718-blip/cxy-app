# 运行时与第三方组件

本包使用 CPython 3.11.15（python-build-standalone / uv 已安装运行时）及 requirements-lock.txt 中固定版本依赖，另含 Frida 17.25.2。Python 许可在 python/lib/python3.11/LICENSE.txt；各 Python 发行包的许可和 METADATA 保留在对应 site-packages/*.dist-info 目录。原有运行时库内的许可文件随包保留。

来源与方法参考：

- CPython：https://www.python.org/ ；构建工具：https://github.com/astral-sh/python-build-standalone
- Frida：https://frida.re/ ；API：https://frida.re/docs/javascript-api/
- 本地数据库一次性准备方法说明：https://github.com/YeJe-cpu/v-local-chat/blob/main/docs/key-extraction-technique.md

本次首次配置和生命周期工具为本工程新增实现，没有复制第三方仓库的抓取脚本。Frida 只在用户主动选择首次准备后用于新建的临时客户端副本；不会作为监听常驻注入器。软件包不包含微信客户端；副本来自接收者本机安装文件。
