$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-ProjectRoot {
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'run.py')) { return $PSScriptRoot }
    return Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
}
function Get-AppStateRoot {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is unavailable.' }
    return [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'GroupChatOrganizer'))
}
function Assert-SafePath {
    param([string]$Path)
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse-point paths are not supported.' }
        }
        $parent = Split-Path $cursor -Parent
        if ($parent -eq $cursor) { break }; $cursor = $parent
    }
}
function Protect-StatePath {
    param([string]$Path)
    Assert-SafePath $Path
    $item = Get-Item -LiteralPath $Path -Force
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($item.PSIsContainer) {
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    } else {
        $acl = New-Object Security.AccessControl.FileSecurity
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','Allow')
    }
    $acl.SetOwner($sid); $acl.SetAccessRuleProtection($true,$false); $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
    $verified = Get-Acl -LiteralPath $Path
    $rules = @($verified.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    if (-not $verified.AreAccessRulesProtected -or $rules.Count -ne 1 -or $rules[0].IdentityReference.Value -ne $sid.Value -or $rules[0].AccessControlType -ne 'Allow') { throw 'Private directory ACL verification failed.' }
}
function Initialize-AppState {
    $root = Get-AppStateRoot; Assert-SafePath $root
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    Protect-StatePath $root
    foreach ($name in @('config','data','logs','private','run')) {
        $path = Join-Path $root $name; Assert-SafePath $path
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
    # Harden existing files as well as new files. Never follow junctions.
    $children = @(Get-SafeChildren $root)
    foreach ($child in $children) { Assert-SafePath $child.FullName }
    foreach ($child in $children) { Protect-StatePath $child.FullName }
    return $root
}
function Ensure-ProjectPython {
    $root = Get-ProjectRoot
    $runtime = Join-Path $root 'runtime\python.exe'
    if (-not (Test-Path -LiteralPath $runtime)) { throw 'Use the complete Windows offline ZIP with its runtime folder. No online installation is performed.' }
    return @{ Exe=$runtime; Prefix=@() }
}
function Resolve-Python { return (Ensure-ProjectPython) }
function Ensure-RuntimeEnvironment {
    $projectRoot = Get-ProjectRoot; Assert-SafePath $projectRoot
    $stateRoot = Initialize-AppState
    $runtimeEnv = Join-Path $stateRoot 'config\runtime.env'
    if (-not (Test-Path -LiteralPath $runtimeEnv)) { Copy-Item -LiteralPath (Join-Path $projectRoot 'windows-default.env') -Destination $runtimeEnv }
    Protect-StatePath $runtimeEnv
    $env:WML_PLATFORM='windows'; $env:WML_ENV_FILE=$runtimeEnv
    $python=Ensure-ProjectPython
    $env:WML_PYTHON=$python.Exe
    $description = & $python.Exe (Join-Path $projectRoot 'tools\windows_runtime.py')
    if ($LASTEXITCODE -ne 0) { throw 'Invalid Windows runtime configuration.' }
    $settings=$description | ConvertFrom-Json
    return @{ProjectRoot=$projectRoot;StateRoot=$stateRoot;RuntimeEnv=$runtimeEnv;Port=[int]$settings.port;Bootstrap=[string]$settings.bootstrap_path;Python=$python.Exe}
}
function Invoke-PythonCommand {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)
    $python=Ensure-ProjectPython; & $python.Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed (exit $LASTEXITCODE)." }
}
function Get-OrganizerHealth {
    param([int]$Port)
    try { return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 } catch { return $null }
}
function Test-PortOccupied {
    param([int]$Port)
    $socket=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$Port)
    try { $socket.Start(); return $false } catch { return $true } finally { $socket.Stop() }
}
function ConvertTo-ProcessArgument {
    param([string]$Value)
    # Windows CommandLineToArgvW quoting, including trailing backslashes.
    return '"' + [regex]::Replace([regex]::Replace($Value,'(\\*)"','$1$1\"'),'(\\+)$','$1$1') + '"'
}
function Get-RecordedProcess {
    param($Context,$Record)
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$Record.pid)" -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    $expectedScript=[IO.Path]::GetFullPath((Join-Path $Context.ProjectRoot 'run.py'))
    if ([IO.Path]::GetFullPath([string]$Record.project_root) -ne [IO.Path]::GetFullPath($Context.ProjectRoot) -or
        [string]$process.ExecutablePath -ne [string]$Record.executable -or
        [string]$process.ExecutablePath -ne [string]$Context.Python -or
        [string]$process.CommandLine -ne [string]$Record.command_line -or
        ([DateTime]$process.CreationDate).ToUniversalTime().Ticks.ToString() -ne [string]$Record.creation_ticks -or
        -not ([string]$process.CommandLine).Contains($expectedScript)) { throw 'Recorded process identity does not match. Refusing to stop or reuse it.' }
    return $process
}
function Open-Organizer {
    param($Context)
    if (Test-Path -LiteralPath $Context.Bootstrap) { Start-Process -FilePath $Context.Bootstrap }
    else { Start-Process "http://127.0.0.1:$($Context.Port)/" }
}

function Get-SafeChildren {
    param([string]$Path)
    Assert-SafePath $Path
    foreach ($child in @(Get-ChildItem -LiteralPath $Path -Force)) {
        Assert-SafePath $child.FullName
        $child
        if ($child.PSIsContainer) { Get-SafeChildren $child.FullName }
    }
}
