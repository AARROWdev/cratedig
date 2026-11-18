# Runs INSIDE Windows Sandbox (started by run-tests.ps1). Never run it on a real PC.
# 1. installer checks (smoke.ps1)  2. black-box tests on the installed app  3. pytest tests\app  4. portable zip
param([string]$Pytest = '', [string]$K = '', [switch]$Quick)
$ErrorActionPreference = 'Continue'
$out = 'C:\out'; $sum = "$out\summary.txt"
if ($env:USERNAME -ne 'WDAGUtilityAccount') { 'FAIL  not in Windows Sandbox, refusing' | Set-Content $sum; 'x' | Set-Content "$out\DONE"; exit 1 }
$py = 'C:\cratedig\.venv-test\Scripts\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
function Check($name, $ok) { "$(if ($ok) {'PASS'} else {'FAIL'})  $name" | Add-Content $sum }
function Log($m) { "$(Get-Date -Format HH:mm:ss)  $m" | Add-Content "$out\progress.log" }
$app = "$env:ProgramFiles\Cratedig"
$silent = '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
$t0 = Get-Date
Log "audio: $(& powershell -NoProfile -ExecutionPolicy Bypass -File C:\cratedig\tests\sandbox\mute.ps1)"   # no test beeps on the host's speakers

Log 'A1-A4: installer checks'
& powershell -NoProfile -ExecutionPolicy Bypass -File C:\cratedig\tests\sandbox\smoke.ps1 -Dist C:\cratedig\dist -Out $out -Keep
Get-Content "$out\results.txt" | Where-Object { $_ -ne 'DONE' } | ForEach-Object { $_ -replace '^(PASS|FAIL)  ', '$1  A ' } | Add-Content $sum

Log 'black-box tests on the installed app'
& $py C:\cratedig\tests\sandbox\blackbox.py all "$app\Cratedig.exe"
Get-Content "$out\blackbox-results.txt" -ErrorAction SilentlyContinue | Add-Content $sum

Log "pytest tests\app $Pytest"
$args_ = @('-m', 'pytest', 'C:\cratedig\tests\app', '-p', 'no:cacheprovider', '-v', '-rs', '--durations=25',
           "--junitxml=$out\pytest.xml", '-o', 'junit_family=xunit1', '--basetemp=C:\cdtmp',
           '-p', 'no:faulthandler')  # its dump of mpv's harmless internal Lua exceptions reads live threads and can crash the run
if ($Pytest) { $args_ += $Pytest -split ' ' }
if ($K) { $args_ += @('-k', ($K -replace '~', ' ')) }  # '~' stands for a space (the .wsb command line can't quote)
if ($Quick) { $args_ += @('-m', 'not big') }
& $py @args_ 2>&1 | Out-File -Encoding utf8 "$out\pytest.log"
$code = $LASTEXITCODE
Check "pytest tests\app (exit $code; see pytest.log)" ($code -eq 0)
Select-String -Path "$out\pytest.log" -Pattern '^(FAILED|ERROR) ' | ForEach-Object { "FAIL  $($_.Line)" } | Add-Content $sum
(Select-String -Path "$out\pytest.log" -Pattern '^=+ .*(passed|failed).* =+$' | Select-Object -Last 1).Line | Add-Content $sum

Log 'uninstall, then A5: portable zip'
Start-Process "$app\unins000.exe" $silent -Wait
$t = 0; while ((Test-Path $app) -and $t -lt 60) { Start-Sleep 1; $t++ }
Check 'A4 settings kept after uninstall' (Test-Path 'HKCU:\Software\Cratedig\Cratedig')
$zip = Get-ChildItem C:\cratedig\dist\Cratedig-*-portable-win64.zip | Select-Object -First 1
Expand-Archive $zip.FullName C:\portable -Force
$exe = Get-ChildItem C:\portable -Recurse -Filter Cratedig.exe | Select-Object -First 1
& $py C:\cratedig\tests\sandbox\blackbox.py portable $exe.FullName
Check 'A5 portable zip opens and plays' ($LASTEXITCODE -eq 0)
Check 'A5 portable run wrote nothing to Program Files' (-not (Test-Path $app))
Check 'A5 portable run registered no Open with entries' (-not (Test-Path 'HKLM:\SOFTWARE\Classes\Cratedig.Media'))
"elapsed $([int]((Get-Date) - $t0).TotalMinutes) min" | Add-Content $sum
Log 'done'
'done' | Set-Content "$out\DONE"
shutdown /s /t 5  # close the Sandbox when finished
