param([switch]$Authenticated,[switch]$IsolatedTest,[int]$TestPort=0,[switch]$NoBrowser)
if ($IsolatedTest -and -not $Authenticated) { throw 'Isolated mode requires authenticated mode.' }
if ($Authenticated -or (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'authenticated_8001.enabled'))) {
 & (Join-Path $PSScriptRoot 'open_8001_authenticated.ps1') -IsolatedTest:$IsolatedTest -TestPort $TestPort -NoBrowser:$NoBrowser
 exit $LASTEXITCODE
}
﻿$ErrorActionPreference = 'Stop'
function Test-TehresursReady {
 try {
  $homeResponse = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8001/' -TimeoutSec 2
  if ($homeResponse.StatusCode -ne 200) { return $false }
  $target = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/api/construction-entities/environment' -TimeoutSec 2
  return ($target.item.database -eq 'ai_excel_agent_test' -and $target.item.schema -eq 'test_construction_identity_stage46')
 } catch { return $false }
}
function Invoke-OpenTehresurs {
 param(
  [scriptblock]$Ready = { Test-TehresursReady },
  [scriptblock]$Listening = { [bool](Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue) },
  [scriptblock]$Launch = {
   $root = 'C:\Projects\excel-ai-agent-8001'
   $script = Join-Path $root 'start_8001_independent.ps1'
   if (-not (Test-Path -LiteralPath $script)) { throw 'Verified launch script is missing.' }
   $logs = Join-Path $root 'backend\output\launcher_8001'
   [void](New-Item -ItemType Directory -Path $logs -Force)
   $id = [guid]::NewGuid().ToString('N')
   Write-Host ('Startup log: ' + (Join-Path $logs $id))
   Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$script,'-Start') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs ($id+'.stdout.log')) -RedirectStandardError (Join-Path $logs ($id+'.stderr.log')) -PassThru
  },
  [scriptblock]$Browser = { Start-Process 'http://127.0.0.1:8001/' },
  [scriptblock]$Delay = { Start-Sleep -Milliseconds 300 }
 )
 if (& $Ready) { Write-Host 'Server 8001 is already running.'; & $Browser; return }
 if (& $Listening) { throw 'Port 8001 is occupied but the application is not ready. Existing process was left untouched.' }
 Write-Host 'Starting server 8001...'
 $process = & $Launch
 $deadline = (Get-Date).AddSeconds(60)
 while ((Get-Date) -lt $deadline) {
  if (& $Ready) { Write-Host 'Server 8001 is ready.'; & $Browser; return }
  if ($null -ne $process -and $process.HasExited) { throw 'Server startup failed. Check the startup log.' }
  & $Delay
 }
 throw 'Server readiness timed out after 60 seconds. Check the startup log. No process was stopped.'
}
if ($MyInvocation.InvocationName -ne '.') {
 try { Invoke-OpenTehresurs; exit 0 }
 catch { Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }
}
