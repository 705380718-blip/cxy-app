. (Join-Path $PSScriptRoot "common.ps1")
$stateRoot = Get-AppStateRoot
$expected = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "GroupChatOrganizer"))
if ($stateRoot -ne $expected -or (Split-Path $stateRoot -Leaf) -ne "GroupChatOrganizer") {
    throw "工具数据目录校验失败，拒绝清理。"
}
if (Test-Path $stateRoot) {
    $item = Get-Item -LiteralPath $stateRoot -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "工具数据目录是重解析点，拒绝清理。"
    }
}
$confirmation = Read-Host "这会删除业务库、DPAPI 密钥、解密快照、配置和日志。输入 DELETE 确认"
if ($confirmation -ne "DELETE") {
    Write-Host "已取消。"
    exit 0
}
& (Join-Path $PSScriptRoot "stop-service.ps1")
if (Test-Path $stateRoot) { @(Get-SafeChildren $stateRoot) | Out-Null; Remove-Item -LiteralPath $stateRoot -Recurse -Force }
Write-Host "本工具数据已删除；微信安装目录和原数据库未被触碰。" -ForegroundColor Green
