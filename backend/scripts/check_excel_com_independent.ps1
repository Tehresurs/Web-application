$ErrorActionPreference = 'Stop'
$previous = @(Get-Process EXCEL -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class IndependentExcelPid {
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@
$excel = $null
$owned = $false
try {
 $excel = New-Object -ComObject Excel.Application
 [uint32]$excelProcessId = 0
 [void][IndependentExcelPid]::GetWindowThreadProcessId([IntPtr]$excel.Hwnd, [ref]$excelProcessId)
 $owned = $excelProcessId -gt 0 -and $excelProcessId -notin $previous
 if (-not $owned) { throw 'Could not prove ownership of Excel instance; existing instance left untouched' }
 $excel.AutomationSecurity = 3
 $excel.EnableEvents = $false
 $excel.DisplayAlerts = $false
 $excel.Visible = $false
 [pscustomobject]@{ ExcelCOM=$true; Version=[string]$excel.Version; OwnInstance=$owned; WorkbooksOpened=[int]$excel.Workbooks.Count; MacrosDisabled=($excel.AutomationSecurity -eq 3); OwnProcessId=$excelProcessId } | ConvertTo-Json
} finally {
 if ($null -ne $excel) {
  if ($owned) { $excel.Quit() }
  [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel)
 }
 [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
