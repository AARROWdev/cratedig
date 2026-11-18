# Runs INSIDE Windows Sandbox (started by run-sandbox.ps1). Never run it on a real PC.
# Install -> Open with registrations -> single instance -> upgrade while running -> uninstall.
# -Keep installs it again at the end (inside.ps1 runs more tests on the installed app).
param([string]$Dist = 'C:\dist', [string]$Out = 'C:\out', [switch]$Keep)
$ErrorActionPreference = 'Continue'
$out = $Out; $log = "$out\results.txt"
function Check($name, $ok) { "$(if ($ok) {'PASS'} else {'FAIL'})  $name" | Add-Content $log }
if ($env:USERNAME -ne 'WDAGUtilityAccount') { 'Not in Windows Sandbox, refusing.' | Set-Content $log; exit 1 }
$setup = Get-ChildItem "$Dist\CratedigSetup-*.exe" | Sort-Object LastWriteTime | Select-Object -Last 1
$app = "$env:ProgramFiles\Cratedig"
$key = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{6F1B7E0A-2C4D-4E8B-9A61-5D3C2B8F7E14}_is1'
$lnk = "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Cratedig.lnk"
$args_ = '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
function OpenWith($ext) { (Get-ItemProperty "HKLM:\SOFTWARE\Classes\$ext\OpenWithProgids" -ErrorAction SilentlyContinue).'Cratedig.Media' -ne $null }
function Procs { @(Get-Process Cratedig -ErrorAction SilentlyContinue) }

$p = Start-Process $setup.FullName ($args_ + "/LOG=$out\install.log") -Wait -PassThru
Check "install exit 0 (got $($p.ExitCode))" ($p.ExitCode -eq 0)
Check 'Cratedig.exe + lib\libmpv-2.dll + lib\ffmpeg.exe installed' ((Test-Path "$app\Cratedig.exe") -and (Test-Path "$app\lib\libmpv-2.dll") -and (Test-Path "$app\lib\ffmpeg.exe"))
Check 'Start Menu shortcut' (Test-Path $lnk)
Check 'Add/Remove Programs entry' (Test-Path $key)
Check 'Open with: .mp3 .wav .flac .mp4 .mkv' ((OpenWith '.mp3') -and (OpenWith '.wav') -and (OpenWith '.flac') -and (OpenWith '.mp4') -and (OpenWith '.mkv'))
Check 'Open command points at the install' ((Get-ItemProperty 'HKLM:\SOFTWARE\Classes\Cratedig.Media\shell\open\command').'(default)' -eq "`"$app\Cratedig.exe`" `"%1`"")
Check 'Default apps: RegisteredApplications' ((Get-ItemProperty HKLM:\SOFTWARE\RegisteredApplications).Cratedig -eq 'Software\Cratedig\Capabilities')
Check 'not made the default player for .mp3' ((Get-ItemProperty 'HKLM:\SOFTWARE\Classes\.mp3' -ErrorAction SilentlyContinue).'(default)' -ne 'Cratedig.Media')

New-Item -ItemType Directory -Force C:\media | Out-Null
& "$app\lib\ffmpeg.exe" -loglevel error -f lavfi -i 'sine=duration=30' C:\media\a.wav 2>$null
& "$app\lib\ffmpeg.exe" -loglevel error -f lavfi -i 'sine=duration=30' C:\media\b.wav 2>$null
$run = Start-Process "$app\Cratedig.exe" 'C:\media\a.wav' -PassThru; Start-Sleep 10
Check 'Cratedig.exe launches with a file and stays up' (-not $run.HasExited)
$second = Start-Process "$app\Cratedig.exe" 'C:\media\b.wav' -PassThru; Start-Sleep 6
Check 'second launch hands off and exits' ($second.HasExited -and $second.ExitCode -eq 0)
Check 'only one Cratedig running' ((Procs).Count -eq 1)
Check 'first window still up' (-not $run.HasExited)

$p = Start-Process $setup.FullName ($args_ + "/LOG=$out\upgrade.log") -Wait -PassThru
Check "upgrade while running exit 0 (got $($p.ExitCode))" ($p.ExitCode -eq 0)
Check 'running Cratedig was closed' ($run.HasExited)
Check 'Cratedig.exe present after upgrade' (Test-Path "$app\Cratedig.exe")

$run = Start-Process "$app\Cratedig.exe" -PassThru; Start-Sleep 8
$p = Start-Process "$app\unins000.exe" $args_ -Wait -PassThru; Start-Sleep 5
Check "uninstall refused while running (exit $($p.ExitCode))" ($p.ExitCode -ne 0)
Check 'install intact after refused uninstall' ((Test-Path "$app\Cratedig.exe") -and (Test-Path $key))
Stop-Process -Id $run.Id -Force -ErrorAction SilentlyContinue; Start-Sleep 2

$p = Start-Process "$app\unins000.exe" $args_ -Wait -PassThru
$t = 0; while ((Test-Path $app) -and $t -lt 60) { Start-Sleep 1; $t++ }
Check "uninstall exit 0 (got $($p.ExitCode))" ($p.ExitCode -eq 0)
Check 'program folder removed' (-not (Test-Path $app))
Check 'Start Menu shortcut removed' (-not (Test-Path $lnk))
Check 'Add/Remove Programs entry removed' (-not (Test-Path $key))
Check 'Open with entries removed' (-not (OpenWith '.mp3') -and -not (OpenWith '.mkv') -and -not (Test-Path 'HKLM:\SOFTWARE\Classes\Cratedig.Media') -and -not (Test-Path 'HKLM:\SOFTWARE\Classes\Applications\Cratedig.exe'))
Check 'Default apps entry removed' (((Get-ItemProperty HKLM:\SOFTWARE\RegisteredApplications).Cratedig -eq $null) -and -not (Test-Path HKLM:\SOFTWARE\Cratedig))
if ($Keep) {
    # the uninstaller runs on from a temp copy for a few seconds after the folder is gone
    $t = 0; while ((Get-Process | Where-Object { $_.Name -like '_iu*' -or $_.Name -like 'unins*' }) -and $t -lt 60) { Start-Sleep 1; $t++ }
    $p = Start-Process $setup.FullName ($args_ + "/LOG=$out\reinstall.log") -Wait -PassThru
    Check "reinstall for the next tests (exit $($p.ExitCode))" ($p.ExitCode -eq 0 -and (Test-Path "$app\Cratedig.exe"))
}
'DONE' | Add-Content $log
