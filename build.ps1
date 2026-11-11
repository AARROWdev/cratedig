# Builds the portable Windows version: build\dist\Cratedig\Cratedig.exe (+ lib\libmpv-2.dll, lib\ffmpeg.exe)
# and zips it to build\Cratedig-v<version>-portable-win64.zip
# Needs: .venv with requirements + pyinstaller, lib\libmpv-2.dll, ffmpeg on PATH.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$version = (Select-String -Path cratedig.py -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value

.\.venv\Scripts\python -m PyInstaller --noconfirm --windowed --name Cratedig `
    --distpath build\dist --workpath build\work --specpath build cratedig.py

$dist = 'build\dist\Cratedig'
New-Item -ItemType Directory -Force "$dist\lib" | Out-Null
Copy-Item lib\libmpv-2.dll "$dist\lib\"
Copy-Item (Get-Command ffmpeg).Source "$dist\lib\"
Copy-Item README.md $dist

$zip = "build\Cratedig-v$version-portable-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $dist -DestinationPath $zip
Write-Host "Built $zip"
