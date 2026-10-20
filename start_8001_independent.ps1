param([switch]$Start,[switch]$Authenticated,[switch]$IsolatedTest,[int]$TestPort=0)
if ($IsolatedTest -and -not $Authenticated) { throw 'Isolated mode requires authenticated mode.' }
if ((Test-Path -LiteralPath (Join-Path $PSScriptRoot 'authenticated_8001.enabled')) -or $Authenticated) {
 $ErrorActionPreference = 'Stop'
 $python = Join-Path $PSScriptRoot 'backend.venv\Scripts\python.exe'
 $launcher = Join-Path $PSScriptRoot 'run_8001_authenticated.py'
 $extra = @()
 $port = 8001
 if ($IsolatedTest) {
  if ($env:AUTH_ISOLATED_WORKER -ne '1' -or $TestPort -in @(8000,8001) -or $TestPort -lt 1024 -or $TestPort -gt 65535) { throw 'Restricted isolated harness required.' }
  $port=$TestPort; $extra=@('--isolated-test','--port',"$port")
 } elseif ($TestPort -ne 0) { throw 'Production port is fixed.' }
 & $python -B $launcher --check @extra
 if ($LASTEXITCODE -ne 0) { throw 'Protected runtime/configuration check failed.' }
 if (-not $Start) { exit 0 }
 if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw 'Port occupied; nothing stopped.' }
 & $python -B $launcher --start @extra
 exit $LASTEXITCODE
}
$ErrorActionPreference = 'Stop'
$root = 'C:\Projects\excel-ai-agent-8001'
$python = Join-Path $root 'backend.venv\Scripts\python.exe'
$probe = Join-Path $root 'backend\scripts\check_independent_runtime.py'
$launcher = 'C:\Projects\run_report_review_8001.py'
if ($PSScriptRoot -ne $root) { throw 'Unexpected launcher directory' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Independent Python not found' }
& $python -B $probe
if ($LASTEXITCODE -ne 0) { throw 'Runtime/configuration check failed' }
if (-not $Start) { Write-Output 'CHECK ONLY. No server started. Use -Start after an approved switch.'; exit 0 }
if (Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue) { throw 'Port 8001 is occupied. Nothing stopped or replaced.' }
Set-Location -LiteralPath $root
& $python -B $launcher
exit $LASTEXITCODE
