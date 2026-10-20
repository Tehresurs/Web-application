$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '..\..\open_tehresurs_8001.ps1')
function Assert-True($condition,$message) { if (-not $condition) { throw $message } }
$state=@{Launch=0;Browser=0}
Invoke-OpenTehresurs -Ready {$true} -Listening {throw 'Must not inspect port after successful readiness'} -Launch {$state.Launch++} -Browser {$state.Browser++}
Assert-True ($state.Launch -eq 0 -and $state.Browser -eq 1) 'Already-running scenario failed'
$state=@{Launch=0;Browser=0;Checks=0}
Invoke-OpenTehresurs -Ready {$state.Checks++;$state.Checks -ge 3} -Listening {$false} -Launch {$state.Launch++;[pscustomobject]@{HasExited=$false}} -Browser {$state.Browser++;Assert-True ($state.Checks -ge 3) 'Browser opened too early'} -Delay {}
Assert-True ($state.Launch -eq 1 -and $state.Browser -eq 1) 'Stopped-server simulation failed'
$state=@{Launch=0;Browser=0};$caught=$false
try { Invoke-OpenTehresurs -Ready {$false} -Listening {$true} -Launch {$state.Launch++} -Browser {$state.Browser++} } catch { $caught=$true }
Assert-True ($caught -and $state.Launch -eq 0 -and $state.Browser -eq 0) 'Occupied wrong server scenario failed'
$state=@{Browser=0};$caught=$false
try { Invoke-OpenTehresurs -Ready {$false} -Listening {$false} -Launch {[pscustomobject]@{HasExited=$true}} -Browser {$state.Browser++} -Delay {} } catch { $caught=$true }
Assert-True ($caught -and $state.Browser -eq 0) 'Startup error must not open browser'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
foreach($name in 'start_tehresurs_8001.bat','open_tehresurs_8001.ps1') {
 $text=Get-Content (Join-Path $root $name) -Raw
 Assert-True ($text -notmatch '\b(del|erase|rmdir|taskkill|Stop-Process|Remove-Item|pg_ctl|psql)\b') 'Forbidden command found'
 Assert-True ($text -notmatch '127\.0\.0\.1:8000|localhost:8000|excel-ai-agent\\backend\\.venv') 'Old server/runtime reference found'
}
Assert-True (Test-TehresursReady) 'Read-only live readiness failed'
Write-Output 'PASS: 4 branch tests, static safety checks, live readiness. No simulated launch started a server.'
