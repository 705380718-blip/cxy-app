. (Join-Path $PSScriptRoot 'common.ps1')
$context=Ensure-RuntimeEnvironment
Write-Host 'Stop the OLD wxauto tool and preserve its original folder before exporting.'
$database=Read-Host 'Full path to the OLD tool database (.db)'
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) { throw 'Legacy database not found.' }
$output=Join-Path $context.StateRoot ('private\legacy-export-'+[DateTime]::Now.ToString('yyyyMMdd-HHmmss-fff'))
Invoke-PythonCommand -Arguments @((Join-Path $context.ProjectRoot 'tools\export_legacy_windows.py'),'--database',$database,'--output',$output)
Write-Host "Exported to: $output"
Write-Host 'Use export-index.json to select group CSVs for import. Prior reviews remain in legacy-review-history.json.'
