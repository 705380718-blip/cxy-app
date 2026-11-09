. (Join-Path $PSScriptRoot 'common.ps1')
$context=Ensure-RuntimeEnvironment
$mutex=New-Object Threading.Mutex($false,('Local\WechatDelivery-'+[Security.Principal.WindowsIdentity]::GetCurrent().User.Value))
$acquired=$false
try {
    try { $acquired=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $acquired=$true }
    if (-not $acquired) { throw 'Another launcher operation is in progress.' }
$recordPath=Join-Path $context.StateRoot 'run\server.json'
if (-not (Test-Path -LiteralPath $recordPath)) { Write-Host 'No instance record.';return }
$record=Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json
$process=Get-RecordedProcess $context $record
if ($process) {
    Stop-Process -Id ([int]$process.ProcessId) -ErrorAction Stop
    Wait-Process -Id ([int]$process.ProcessId) -Timeout 10 -ErrorAction SilentlyContinue
    if (Get-RecordedProcess $context $record) { throw 'Application is still running; instance record retained.' }
}
Remove-Item -LiteralPath $recordPath
# An unconsumed bootstrap is a credential. Remove it after stopping.
if (Test-Path -LiteralPath $context.Bootstrap) { Remove-Item -LiteralPath $context.Bootstrap }
Write-Host 'Application stopped. Messages and configuration are preserved.'

} finally { if ($acquired) { $mutex.ReleaseMutex() };$mutex.Dispose() }
