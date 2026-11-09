param([switch]$NoBrowser,[switch]$NoTray)
. (Join-Path $PSScriptRoot 'common.ps1')
$context=Ensure-RuntimeEnvironment
$mutexName='Local\WechatDelivery-'+[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$mutex=New-Object Threading.Mutex($false,$mutexName)
$acquired=$false
try {
    try { $acquired=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $acquired=$true }
    if (-not $acquired) { throw 'Another launcher is starting this application.' }
    $recordPath=Join-Path $context.StateRoot 'run\server.json'
    if (Test-Path -LiteralPath $recordPath) {
        $record=Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json
        $existing=Get-RecordedProcess $context $record
        if ($existing) {
            $health=Get-OrganizerHealth ([int]$record.port)
            if (-not $health -or $health.product -ne 'group-chat-organizer-local-listener' -or $health.instance_id -ne $record.instance_id -or -not $health.session_required) { throw 'Running instance failed identity/authentication verification.' }
            $context.Port=[int]$record.port
            if (-not $NoBrowser) { Open-Organizer $context }; return
        }
        Remove-Item -LiteralPath $recordPath
    }
    if (Test-PortOccupied $context.Port) { throw 'Configured port is already occupied. Change WML_PORT in the private runtime.env; no other process was stopped.' }
    $env:WML_INSTANCE_ID=[Guid]::NewGuid().ToString('N')
    $script=[IO.Path]::GetFullPath((Join-Path $context.ProjectRoot 'run.py'))
    $process=Start-Process -FilePath $context.Python -ArgumentList (ConvertTo-ProcessArgument $script) -WorkingDirectory $context.ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $context.StateRoot 'logs\app.log') -RedirectStandardError (Join-Path $context.StateRoot 'logs\app-error.log') -PassThru
    $native=Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
    $record=@{pid=$process.Id;project_root=$context.ProjectRoot;executable=[string]$native.ExecutablePath;command_line=[string]$native.CommandLine;creation_ticks=([DateTime]$native.CreationDate).ToUniversalTime().Ticks.ToString();instance_id=$env:WML_INSTANCE_ID;port=$context.Port}
    $record | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $recordPath
    Protect-StatePath $recordPath
    $ready=$false
    for ($i=0;$i -lt 120;$i++) {
        if ($process.HasExited) { break }
        $health=Get-OrganizerHealth $context.Port
        if ($health -and $health.product -eq 'group-chat-organizer-local-listener' -and $health.instance_id -eq $record.instance_id -and $health.session_required -and (Test-Path -LiteralPath $context.Bootstrap)) { $ready=$true;break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) {
        $owned=Get-RecordedProcess $context $record
        if ($owned) { Stop-Process -Id ([int]$owned.ProcessId) }
        Remove-Item -LiteralPath $recordPath -ErrorAction SilentlyContinue
        throw 'Startup failed. Inspect the private logs directory.'
    }
    if (-not $NoBrowser) { Open-Organizer $context }
    if (-not $NoTray) {
        $tray=Join-Path $PSScriptRoot 'tray.ps1'
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoProfile -STA -File '+(ConvertTo-ProcessArgument $tray)) | Out-Null
    }
    Write-Host "Started: http://127.0.0.1:$($context.Port)/"
} finally { if ($acquired) { $mutex.ReleaseMutex() };$mutex.Dispose() }
