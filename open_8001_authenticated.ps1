param([switch]$IsolatedTest,[int]$TestPort=0,[switch]$NoBrowser)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$port=8001
if ($IsolatedTest) {
 if ($env:AUTH_ISOLATED_WORKER -ne '1' -or $TestPort -in @(8000,8001) -or $TestPort -lt 1024 -or $TestPort -gt 65535) { throw 'Restricted isolated harness required.' }
 $port=$TestPort
} elseif ($TestPort -ne 0) { throw 'Production port is fixed.' }
$launcher=Join-Path $root 'run_8001_authenticated.py'
$python=Join-Path $root 'backend.venv\Scripts\python.exe'
$state=Join-Path $root ("backend\output\launcher_8001\authenticated-$port.json")
$url="http://127.0.0.1:$port/"
function Test-ProtectedReady {
 $script:ReadyStage='listener'
 try {
  $listener=Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Where-Object LocalAddress -eq '127.0.0.1'
  if (@($listener).Count -ne 1 -or -not (Test-Path -LiteralPath $state)) { return $false }
  $script:ReadyStage='process-and-manifest'
  $info=Get-Content -Raw -LiteralPath $state | ConvertFrom-Json
  $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
  if ($null -eq $proc -or $info.pid -ne $listener.OwningProcess -or $info.launcher -ne $launcher -or $info.python -ne $python -or $info.port -ne $port -or $info.host -ne '127.0.0.1' -or -not $info.protected) { return $false }
  if ($proc.CommandLine -notlike "*$launcher*" -or $proc.CommandLine -notlike "*$python*") { return $false }
  $script:ReadyStage='launcher-hash'
  if ($info.launcher_sha256 -ne (Get-FileHash -Algorithm SHA256 -LiteralPath $launcher).Hash.ToLower()) { return $false }
  $script:ReadyStage='target'
  if ($IsolatedTest) {
   if ($info.mode -ne 'isolated' -or $info.database -ne $env:DB_NAME -or $info.database -notlike 'auth_stage3_*') { return $false }
  } elseif ($info.mode -ne 'authenticated' -or $info.database -ne 'ai_excel_agent_test') { return $false }
  if ($info.schema -ne 'test_construction_identity_stage46') { return $false }
  $script:ReadyStage='http'
  Add-Type -AssemblyName System.Net.Http
  $handler=[System.Net.Http.HttpClientHandler]::new()
  $handler.AllowAutoRedirect=$false;$handler.UseCookies=$false;$handler.UseProxy=$false
  $client=[System.Net.Http.HttpClient]::new($handler);$client.Timeout=[TimeSpan]::FromSeconds(2)
  try {
   $login=$client.GetAsync($url+'login').GetAwaiter().GetResult()
   $me=$client.GetAsync($url+'api/auth/me').GetAwaiter().GetResult()
   return ([int]$login.StatusCode -eq 200 -and $login.Content.ReadAsStringAsync().GetAwaiter().GetResult().Contains('authLoginForm') -and [int]$me.StatusCode -eq 401)
  } finally { $client.Dispose() }
 } catch { return $false }
}
function Open-ProtectedBrowser {
 if ($NoBrowser) { Write-Output ('Browser suppressed for check: '+$url) } else { Start-Process $url }
}
$launchMutex=[System.Threading.Mutex]::new($false,('Local\TehresursAuthenticatedLaunch-'+$port))
$mutexHeld=$false
try {
 try { $mutexHeld=$launchMutex.WaitOne(60000) } catch [System.Threading.AbandonedMutexException] { $mutexHeld=$true }
 if (-not $mutexHeld) { throw 'Another launch check is still running.' }
 if (Test-ProtectedReady) { Write-Output 'Protected server already running; no second process.';Open-ProtectedBrowser;exit 0 }
 if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw 'Port occupied by an unverified or unprotected process. Nothing stopped or replaced.' }
 $logs=Join-Path $root 'backend\output\launcher_8001';[void](New-Item -ItemType Directory -Force -Path $logs)
 $id=[guid]::NewGuid().ToString('N')
 $arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $root 'start_8001_independent.ps1'),'-Start','-Authenticated')
 if ($IsolatedTest) { $arguments+=@('-IsolatedTest','-TestPort',"$port") }
 $child=Start-Process powershell.exe -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "$id.stdout.log") -RedirectStandardError (Join-Path $logs "$id.stderr.log") -PassThru
 $deadline=(Get-Date).AddSeconds(50)
 while ((Get-Date) -lt $deadline) {
  if (Test-ProtectedReady) { Write-Output 'Protected server ready.';Open-ProtectedBrowser;exit 0 }
  if ($child.HasExited) { throw 'Protected launch failed. See the launcher log.' }
  Start-Sleep -Milliseconds 250
 }
 throw ('Protected readiness timed out at '+$script:ReadyStage+'. No process was stopped.')
} catch { Write-Host ('ERROR: '+$_.Exception.Message) -ForegroundColor Red;exit 1 }

finally { if ($mutexHeld) { $launchMutex.ReleaseMutex() };$launchMutex.Dispose() }
