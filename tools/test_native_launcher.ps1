param([string]$Build = (Join-Path $PSScriptRoot '..\output\native-build\Release'))
$ErrorActionPreference = 'Stop'
$npvRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$npvRun = Join-Path $npvRoot ('output\validation\launcher-' + [Guid]::NewGuid().ToString('N'))
$npvGame = Join-Path $npvRun 'Jogo com espacos'
$npvBin = Join-Path $npvGame 'bin\x64'
$npvPlugin = Join-Path $npvGame 'red4ext\plugins\NPVMaker'
$npvRuntime = Join-Path $npvPlugin 'runtime'
New-Item -ItemType Directory -Force -Path $npvBin,$npvRuntime | Out-Null
Copy-Item -LiteralPath (Join-Path $Build 'NPVMakerLauncherHost.exe') -Destination (Join-Path $npvBin 'Cyberpunk2077.exe')
Copy-Item -LiteralPath (Join-Path $Build 'NPVMakerRuntime.dll') -Destination $npvPlugin
Copy-Item -LiteralPath (Join-Path $Build 'NPVMakerTestConverter.exe') -Destination (Join-Path $npvRuntime 'NPVMakerConverter.exe')
& (Join-Path $npvBin 'Cyberpunk2077.exe') (Join-Path $npvPlugin 'NPVMakerRuntime.dll')
if ($LASTEXITCODE -ne 0) { throw "Launcher lifecycle test failed: $LASTEXITCODE" }
$npvArguments = Get-Content -LiteralPath (Join-Path $npvPlugin 'launcher-test.txt')
if ($npvArguments[1] -ne '--game-root' -or $npvArguments[2] -ne $npvGame -or
    $npvArguments[3] -ne '--plugin-root' -or $npvArguments[4] -ne $npvPlugin -or
    $npvArguments[5] -ne '--parent-pid') { throw 'Bundled converter received incorrect installation paths' }

$npvMissing = Join-Path $npvGame 'red4ext\plugins\MissingRuntime'
New-Item -ItemType Directory -Force -Path $npvMissing | Out-Null
Copy-Item -LiteralPath (Join-Path $Build 'NPVMakerRuntime.dll') -Destination $npvMissing
& (Join-Path $npvBin 'Cyberpunk2077.exe') (Join-Path $npvMissing 'NPVMakerRuntime.dll')
if ($LASTEXITCODE -ne 4) { throw 'Missing bundled runtime did not fail explicitly' }
$npvReport = @{
    isolated_test = $true
    game_loaded = $false
    converter_is_test_double = $true
    paths_discovered_without_development_drive = $true
    paths_with_spaces_preserved = $true
    child_started_automatically = $true
    child_stopped_on_unload = $true
    missing_runtime_rejected = $true
    public_release_ready = $false
}
$npvReport | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $npvRun 'result.json') -Encoding utf8
Write-Output (Join-Path $npvRun 'result.json')
