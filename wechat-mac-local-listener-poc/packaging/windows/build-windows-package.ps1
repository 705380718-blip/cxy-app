param([Parameter(Mandatory=$true)][string]$PythonEmbeddableZip,[Parameter(Mandatory=$true)][string]$Wheelhouse,[string]$OutputDirectory='dist\windows')
$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
# Developer build only: uses installed Python with packaging, never installs dependencies.
& py.exe -3 (Join-Path $root 'scripts\build-windows-package.py') --runtime $PythonEmbeddableZip --wheelhouse $Wheelhouse --output $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Offline package build failed.' }
