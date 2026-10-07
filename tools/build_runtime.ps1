param(
    [string]$Python = "",
    # Kept for old command lines; WolvenKit and .NET are no longer staged (see below).
    [switch]$SkipDependencies,
    # Keep the converter already frozen in output\frozen: a new freeze changes
    # its SHA256 and invalidates the standalone validation of that exact exe.
    [switch]$ReuseFrozen
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (!$Python) { $Python = Join-Path $root 'tools\build-env\Scripts\python.exe' }
$destination = Join-Path $root 'output\standalone\red4ext\plugins\NPVMaker'
$runtime = Join-Path $destination 'runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
if ($ReuseFrozen) {
    if (!(Test-Path (Join-Path $root 'output\frozen\NPVMakerConverter\NPVMakerConverter.exe'))) { throw 'No frozen converter to reuse' }
} else {
& $Python -m PyInstaller --noconfirm --onedir --name NPVMakerConverter --distpath (Join-Path $root 'output\frozen') --workpath (Join-Path $root 'output\freeze-work') --specpath (Join-Path $root 'output\freeze-work') (Join-Path $PSScriptRoot 'runtime_entry.py')
if ($LASTEXITCODE) { throw 'Converter freeze failed' }
}
Copy-Item (Join-Path $root 'output\frozen\NPVMakerConverter\*') -Destination $runtime -Recurse -Force
Copy-Item (Join-Path $root 'output\native-build\Release\NPVMakerRuntime.dll') -Destination $destination -Force
# WolvenKit and .NET never go in the NPV Maker package (maintainer's request, WORKFLOW section 20):
# the player sets them up from the panel (tools\wolvenkit_setup.py). Copies staged by older builds go.
foreach ($old in 'wolvenkit', 'dotnet') {
    $stale = Join-Path $runtime $old
    if (Test-Path $stale) { Remove-Item -Recurse -Force $stale }
}
# 0.5.0: no CET (author decision 30/09/2026). The game side is REDscript with RedFileSystem; a CET folder
# staged by an older build is removed so it can never enter the package again.
$bin = Join-Path $root 'output\standalone\bin'
if (Test-Path $bin) { Remove-Item -Recurse -Force $bin }
$reds = Join-Path $root 'output\standalone\r6\scripts\NPVMaker'
New-Item -ItemType Directory -Force -Path $reds | Out-Null
Get-ChildItem $reds -Filter '*.reds' | Remove-Item -Force
Copy-Item (Join-Path $root 'src\redscript\*.reds') -Destination $reds -Force
Write-Output "Standalone build staged at $(Join-Path $root 'output\standalone')"
