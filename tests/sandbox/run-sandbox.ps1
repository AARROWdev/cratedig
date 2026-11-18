# Runs tests\sandbox\smoke.ps1 in a fresh Windows Sandbox against dist\CratedigSetup-*.exe (run build.ps1 first).
# The sandbox is thrown away afterwards; results land in a temp folder on this PC.
$ErrorActionPreference = 'Stop'
$root = Resolve-Path "$PSScriptRoot\..\.."
$out = Join-Path $env:TEMP "cratedig-sandbox-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory $out | Out-Null
$wsb = @"
<Configuration>
  <Networking>Disable</Networking>
  <MappedFolders>
    <MappedFolder><HostFolder>$root\dist</HostFolder><SandboxFolder>C:\dist</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$PSScriptRoot</HostFolder><SandboxFolder>C:\tests</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$out</HostFolder><SandboxFolder>C:\out</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand><Command>powershell -NoProfile -ExecutionPolicy Bypass -File C:\tests\smoke.ps1</Command></LogonCommand>
</Configuration>
"@
$wsb | Set-Content "$out\cratedig.wsb" -Encoding UTF8
Start-Process "$out\cratedig.wsb"
$log = "$out\results.txt"
for ($i = 0; $i -lt 600 -and -not ((Test-Path $log) -and (Select-String -Path $log -Pattern '^DONE$|refusing' -Quiet -ErrorAction SilentlyContinue)); $i++) { Start-Sleep 1 }
if (Test-Path $log) { Get-Content $log } else { throw "No results after 10 minutes ($out)" }
Get-Process WindowsSandbox*, vmmem* -ErrorAction SilentlyContinue | Where-Object Name -like 'WindowsSandbox*' | Stop-Process -Force
if (Select-String -Path $log -Pattern '^FAIL' -Quiet) { exit 1 }
