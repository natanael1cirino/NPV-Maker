param([string]$CMake = '')
$ErrorActionPreference = 'Stop'
$npvRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $CMake) {
    $npvFound = Get-Command cmake.exe -ErrorAction SilentlyContinue
    if ($npvFound) { $CMake = $npvFound.Source }
    else {
        $npvVsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
        if (-not (Test-Path -LiteralPath $npvVsWhere)) { throw 'CMake ou Visual Studio Build Tools indisponivel.' }
        $npvVs = & $npvVsWhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        $CMake = Join-Path $npvVs 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
    }
}
$npvBuild = Join-Path $npvRoot 'output\native-build'
& $CMake -S (Join-Path $npvRoot 'src\native') -B $npvBuild -G 'Visual Studio 17 2022' -A x64
if ($LASTEXITCODE -ne 0) { throw 'Falha ao configurar runtime nativo.' }
& $CMake --build $npvBuild --config Release
if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar runtime nativo.' }
& (Join-Path $PSScriptRoot 'test_native_launcher.ps1') -Build (Join-Path $npvBuild 'Release')
