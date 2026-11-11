# Installs the portable build to %LOCALAPPDATA%\Programs\Cratedig and registers it with Windows
# so it shows up in "Open with" and Settings > Default apps for every audio/video type.
# Per-user only (HKCU), no admin needed. Run again after a rebuild to update the installed copy.
param([string]$Source = "$PSScriptRoot\build\dist\Cratedig")
$ErrorActionPreference = 'Stop'

$dest = Join-Path $env:LOCALAPPDATA 'Programs\Cratedig'
Get-Process Cratedig -ErrorAction SilentlyContinue | Stop-Process -Force
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
Copy-Item $Source $dest -Recurse
$exe = Join-Path $dest 'Cratedig.exe'

$exts = 'wav mp3 flac aiff aif m4a aac ogg oga opus wma alac ape wv mka mid midi ' +
        'mp4 mkv mov avi webm wmv m4v flv mpg mpeg ts m2ts 3gp vob ogv' -split ' '
$cmd = "`"$exe`" `"%1`""
$progid = 'Cratedig.Media'
$cls = 'HKCU:\Software\Classes'

function Set-Key($path, $name, $value) {
    if (-not (Test-Path $path)) { New-Item $path -Force | Out-Null }
    if ($name -eq '(default)') { Set-Item $path -Value $value }
    else { New-ItemProperty $path -Name $name -Value $value -PropertyType String -Force | Out-Null }
}

# ProgID
Set-Key "$cls\$progid" '(default)' 'Cratedig media file'
Set-Key "$cls\$progid\DefaultIcon" '(default)' "`"$exe`",0"
Set-Key "$cls\$progid\shell\open\command" '(default)' $cmd

# Applications entry (Open with list)
$app = "$cls\Applications\Cratedig.exe"
Set-Key $app 'FriendlyAppName' 'Cratedig'
Set-Key "$app\shell\open\command" '(default)' $cmd
foreach ($e in $exts) { Set-Key "$app\SupportedTypes" ".$e" '' }

# Each extension lists Cratedig as a handler
foreach ($e in $exts) { Set-Key "$cls\.$e\OpenWithProgids" $progid '' }

# Capabilities (Settings > Default apps > Set defaults by app)
$cap = 'HKCU:\Software\Cratedig\Capabilities'
Set-Key $cap 'ApplicationName' 'Cratedig'
Set-Key $cap 'ApplicationDescription' 'File explorer + media player'
foreach ($e in $exts) { Set-Key "$cap\FileAssociations" ".$e" $progid }
Set-Key 'HKCU:\Software\RegisteredApplications' 'Cratedig' 'Software\Cratedig\Capabilities'

# Tell Explorer associations changed
Add-Type -Namespace W -Name S -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, int f, IntPtr a, IntPtr b);'
[W.S]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Host "Installed to $dest and registered $($exts.Count) types"
