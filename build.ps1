# Builds Cratedig for Windows:
#   build\dist\Cratedig\Cratedig.exe          the app (PyInstaller one-folder build, with lib\mpv-2.dll + lib\ffmpeg.exe)
#   dist\CratedigSetup-<ver>.exe              the installer (Inno Setup 6)
#   dist\Cratedig-<ver>-portable-win64.zip    the portable version
# Needs: .venv with requirements + pyinstaller, lib\libmpv-2.dll, ffmpeg on PATH,
# and Inno Setup 6 (winget install JRSoftware.InnoSetup).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Remove-Item dist -Recurse -Force -ErrorAction SilentlyContinue  # only this build's downloads end up in dist

$m = Select-String -Path cratedig.py -Pattern '^VERSION = "([^"]+)"'
if (-not $m) { throw 'VERSION not found in cratedig.py' }
$ver = $m.Matches[0].Groups[1].Value

.\.venv\Scripts\python -m PyInstaller --noconfirm --windowed --name Cratedig --icon "$PSScriptRoot\cratedig.ico" `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtMultimedia --exclude-module PIL `
    --distpath build\dist --workpath build\work --specpath build cratedig.py
if ($LASTEXITCODE) { throw "PyInstaller failed ($LASTEXITCODE)" }

$app = 'build\dist\Cratedig'
New-Item -ItemType Directory -Force "$app\lib" | Out-Null
Copy-Item lib\libmpv-2.dll "$app\lib\mpv-2.dll"   # python-mpv looks for mpv-2.dll first, across PATH: this name keeps the bundled one first
Copy-Item (Get-Command ffmpeg).Source "$app\lib\"
Copy-Item README.md, LICENSE, cratedig.ico $app

$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) { throw 'Inno Setup 6 not found (winget install JRSoftware.InnoSetup)' }
New-Item -ItemType Directory -Force dist | Out-Null
& $iscc /Q "/DAppVersion=$ver" installer\cratedig.iss
if ($LASTEXITCODE) { throw "Inno Setup failed ($LASTEXITCODE)" }

$zip = "dist\Cratedig-$ver-portable-win64.zip"
Compress-Archive -Path $app -DestinationPath $zip -Force

Write-Host "Built $app\Cratedig.exe, dist\CratedigSetup-$ver.exe, $zip"
