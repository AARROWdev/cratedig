# Runs the whole Cratedig test suite in a fresh Windows Sandbox:
#   installer checks (install, Open with, single instance, upgrade while running, uninstall), black-box tests
#   against the installed Cratedig.exe, every test in tests\app (pytest), and the portable zip.
# Nothing runs on this PC. Results land in a temp folder (printed at the end).
# Needs: build.ps1 run first, and .venv-test
# (python -m venv .venv-test; .venv-test\Scripts\pip install -r requirements.txt pytest pywinauto psutil).
param([string]$Pytest = '', [string]$K = '', [switch]$Quick, [switch]$NoWait, [int]$Minutes = 180)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$py = (Get-Content "$root\.venv-test\pyvenv.cfg" | Where-Object { $_ -like 'home*' }) -replace '^home\s*=\s*', ''
if (-not (Test-Path "$root\dist\CratedigSetup-*.exe")) { throw 'Run build.ps1 first' }

$out = Join-Path $env:TEMP "cratedig-tests-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory $out | Out-Null
$wsb = @"
<Configuration>
  <Networking>Disable</Networking>
  <MemoryInMB>8192</MemoryInMB>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <AudioInput>Disable</AudioInput>
  <MappedFolders>
    <MappedFolder><HostFolder>$root</HostFolder><SandboxFolder>C:\cratedig</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$py</HostFolder><SandboxFolder>$py</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$out</HostFolder><SandboxFolder>C:\out</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand><Command>powershell -NoProfile -ExecutionPolicy Bypass -File C:\cratedig\tests\sandbox\inside.ps1 -Pytest "$Pytest" -K "$K" $(if ($Quick) {'-Quick'})</Command></LogonCommand>
</Configuration>
"@
$wsb | Set-Content "$out\cratedig.wsb" -Encoding UTF8
# only one Sandbox can run at a time: a leftover one would swallow this start
Get-Process WindowsSandbox* -ErrorAction SilentlyContinue | Stop-Process -Force
for ($i = 0; $i -lt 30 -and (Get-Process WindowsSandbox* -ErrorAction SilentlyContinue); $i++) { Start-Sleep 1 }
Start-Sleep 5
Start-Process "$out\cratedig.wsb"
# Keep the Sandbox window minimized and never activate it: the PC's owner keeps using their mouse and keyboard.
Add-Type -Namespace CdWin -Name U -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
[DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
'@
$until = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $until) {
    foreach ($p in Get-Process WindowsSandboxClient -ErrorAction SilentlyContinue) {
        if ($p.MainWindowHandle -ne 0 -and -not [CdWin.U]::IsIconic($p.MainWindowHandle)) {
            [void][CdWin.U]::ShowWindow($p.MainWindowHandle, 7)
        }
    }
    Start-Sleep -Milliseconds 300
}
Write-Host "Sandbox started; results in $out"
if ($NoWait) { $out; exit 0 }
$done = "$out\DONE"
for ($i = 0; $i -lt $Minutes * 12 -and -not (Test-Path $done); $i++) { Start-Sleep 5 }
Get-Process WindowsSandbox* -ErrorAction SilentlyContinue | Stop-Process -Force
if (-not (Test-Path $done)) { Write-Host "TIMEOUT after $Minutes minutes"; exit 2 }
Get-Content "$out\summary.txt"
if (Select-String -Path "$out\summary.txt" -Pattern '^FAIL' -Quiet) { exit 1 }
