. (Join-Path $PSScriptRoot "common.ps1")
$context = Ensure-RuntimeEnvironment
$diagnostic = Join-Path ([Environment]::GetFolderPath("Desktop")) "wechat-windows-diagnostic.json"

Write-Host "正在生成不含密钥、账号名和聊天正文的诊断文件……" -ForegroundColor Cyan
Invoke-PythonCommand -Arguments @((Join-Path $context.ProjectRoot "tools\windows_key_prep.py"), "diagnose", "--output", $diagnostic)
Write-Host "诊断文件：$diagnostic" -ForegroundColor Green
Write-Host "首次适配请先把该文件带回开发环境；未创建精确 enabled profile 前，解码会保持阻断。"

$continue = Read-Host "如果已经拿到本版本 profile 和候选密钥 JSON，输入 PREPARE；否则直接回车退出"
if ($continue -ne "PREPARE") { exit 0 }
$profileId = Read-Host "请输入 decoder profile id"
$candidatePath = Read-Host "请输入候选密钥 JSON 的完整路径"
if (-not (Test-Path -LiteralPath $candidatePath -PathType Leaf)) { throw "候选密钥文件不存在。" }

Invoke-PythonCommand -Arguments @(
    (Join-Path $context.ProjectRoot "tools\windows_key_prep.py"),
    "prepare", "--profile-id", $profileId, "--candidates", $candidatePath
)
Write-Host "密钥已验证并由当前 Windows 用户的 DPAPI 保护。" -ForegroundColor Green
Write-Host "候选密钥文件不会被工具保存；请按你的安全流程删除原文件。" -ForegroundColor Yellow
