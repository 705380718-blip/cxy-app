. (Join-Path $PSScriptRoot 'common.ps1')
$context=Ensure-RuntimeEnvironment
$output=Join-Path ([Environment]::GetFolderPath('Desktop')) 'wechat-windows-self-test.json'
Invoke-PythonCommand -Arguments @((Join-Path $context.ProjectRoot 'tools\windows_selftest.py'),'--output',$output)
Write-Host "Offline self-test report: $output"
