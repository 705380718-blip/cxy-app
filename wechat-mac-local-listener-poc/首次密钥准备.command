#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "$0")" && pwd)"
python_bin="$app_dir/runtime/bin/python3"
helper="$app_dir/tools/extract_keys.py"
verifier="$app_dir/tools/verify_keys.py"
export PYTHONHOME="$app_dir/runtime"

if [[ ! -x "$python_bin" ]]; then
  osascript -e 'display alert "运行时缺失" message "请使用完整软件包，不要单独复制此文件。" as critical'
  exit 1
fi
if [[ ! -d /Applications/WeChat.app ]]; then
  osascript -e 'display alert "未找到微信" message "请先把官方微信安装到“应用程序”目录并完成登录。" as critical'
  exit 1
fi

answer="$(osascript -e 'button returned of (display dialog "首次准备会复制一份微信到桌面、临时签名，并用 Frida 捕获当前账号的本地数据库密钥。密钥只保存在 ~/.config/wechat-keys.json，不会写入软件包或上传。是否继续？" buttons {"取消", "继续"} default button "取消" with icon caution)')"
if [[ "$answer" != "继续" ]]; then
  exit 0
fi

if "$python_bin" "$helper" --targets all --duration 180; then
  if "$python_bin" "$verifier"; then
    osascript -e 'display alert "密钥准备完成" message "关键数据库已验证。现在可以双击“群聊问题整理”启动软件。"'
  else
    osascript -e 'display alert "没有捕获到有效密钥" message "请保持临时微信副本登录，在倒计时期间依次打开收藏、朋友圈并滚动一次，然后重新运行本命令。" as critical'
    exit 1
  fi
else
  osascript -e 'display alert "密钥准备失败" message "请查看终端末尾的错误提示后重试。只有出现“Done. Keys saved”才表示成功。" as critical'
  exit 1
fi
