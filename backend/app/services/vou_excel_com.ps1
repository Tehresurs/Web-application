param([Parameter(Mandatory=$true)][string]$RequestPath)
$ErrorActionPreference='Stop'
# Scope only this COM worker: Excel's automation model uses English names/formulas.
[Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo('en-US')
[Threading.Thread]::CurrentThread.CurrentUICulture=[Globalization.CultureInfo]::GetCultureInfo('en-US')
$request=Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$result=@{ok=$false;error=$null;excel_process_id=$null;excel_version=$null;forced_cleanup=$false}
$excel=$null;$books=$null;$book=$null;$sheets=$null;$sheet=$null
$ownsExcel=$false;$excelOwnerProcessId=0;$excelStartTicks=0
function Release-Com($value){
    if($null -ne $value -and [Runtime.InteropServices.Marshal]::IsComObject($value)){
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($value)
    }
}
function Write-JsonFile($path,$value){
    [IO.File]::WriteAllText($path,($value|ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
}
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class VouExcelWindow {
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
}
'@
function Write-Stage([string]$stage){$result.stage=$stage;Write-JsonFile $request.result_path $result}

function Set-OwnedExcelPrinter([string]$device){
    $devices=Get-ItemProperty -LiteralPath 'Registry::HKEY_CURRENT_USER\Software\Microsoft\Windows NT\CurrentVersion\Devices'
    $matches=@($devices.PSObject.Properties | Where-Object {
        $_.Value -is [string] -and $_.Value.StartsWith('winspool,') -and
        ($_.Name -eq $device -or $_.Name.StartsWith($device))
    })
    if($matches.Count -ne 1){throw ('Original template printer is missing or ambiguous: '+$device)}
    $name=$matches[0].Name;$port=$matches[0].Value.Split(',')[-1]
    foreach($candidate in @(($name+' ('+$port+')'),($name+' on '+$port),($name+' на '+$port))){
        try{$excel.ActivePrinter=$candidate;return}catch{}
    }
    throw ('Excel cannot select original template printer: '+$name)
}


function Print-Snapshot($target){
    $setup=$null;$names=$null;$items=@()
    try{
        $setup=$target.PageSetup;$area=[string]$setup.PrintArea
        $names=$target.Names
        for($i=1;$i -le $names.Count;$i++){
            $entry=$null
            try{$entry=$names.Item($i);$items+=@{name=[string]$entry.Name;local=[string]$entry.NameLocal;refers_to=[string]$entry.RefersTo}}
            finally{Release-Com $entry}
        }
        return @{area=$area;names=$items}
    }finally{Release-Com $setup;Release-Com $names}
}

function Restore-PrintAreas($areas,$profiles){
    # Excel can initially expose imported print names as ordinary local names.
    # Restore the exact approved ranges through PageSetup before edits so that
    # native row insertion updates their references as well.
    foreach($property in $areas.PSObject.Properties){
        Write-Stage ('print_area_'+$property.Name)
        $printSheet=$null;$printSetup=$null
        try{
            $printSheet=$sheets.Item([string]$property.Name)
            $printSheet.Activate()
            Set-OwnedExcelPrinter ([string]$profiles.($property.Name))
            $excel.PrintCommunication=$false
            # This master imports Print_Area as an ordinary local name. Keeping it
            # beside the native built-in area causes an Excel name-conflict dialog.
            # Replace only that imported representation in the COPY, then restore
            # the exact same approved range as a native print area.
            $localNames=$null
            try{
                $localNames=$printSheet.Names
                for($nameIndex=$localNames.Count;$nameIndex -ge 1;$nameIndex--){
                    $localName=$null
                    try{
                        $localName=$localNames.Item($nameIndex)
                        if([string]$localName.Name -match '(^|!)(?:_xlnm\.)?Print_Area$'){
                            $localName.Delete()
                        }
                    }finally{Release-Com $localName}
                }
            }finally{Release-Com $localNames}
            $printSetup=$printSheet.PageSetup
            $printSetup.PrintArea=[string]$property.Value
            $excel.PrintCommunication=$true
        }finally{Release-Com $printSetup;Release-Com $printSheet}
    }
    $excel.PrintCommunication=$true
}

$previousExcel=@(Get-Process -Name EXCEL -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
try{
    Write-Stage 'create_excel'
    $excel=New-Object -ComObject Excel.Application
    [uint32]$ownerId=0
    [void][VouExcelWindow]::GetWindowThreadProcessId([IntPtr]$excel.Hwnd,[ref]$ownerId)
    $excelOwnerProcessId=[int]$ownerId
    if($excelOwnerProcessId -le 0 -or $previousExcel -contains $excelOwnerProcessId){
        throw 'Excel did not provide a new isolated process; existing user instances will not be used.'
    }
    $ownsExcel=$true
    $excelProcess=Get-Process -Id $excelOwnerProcessId
    $excelStartTicks=$excelProcess.StartTime.ToUniversalTime().Ticks
    Write-JsonFile $request.lease_path @{process_id=$excelOwnerProcessId;start_ticks=$excelStartTicks}
    $result.excel_process_id=$excelOwnerProcessId
    $result.excel_version=[string]$excel.Version
    $excel.Visible=$false
    $excel.DisplayAlerts=$false
    $excel.EnableEvents=$false
    $excel.AutomationSecurity=3
    $excel.AskToUpdateLinks=$false
    $excel.IgnoreRemoteRequests=$true
    $books=$excel.Workbooks
    # UpdateLinks=0; macros are force-disabled before opening the copy.
    Write-Stage 'open_copy'
    $isVerify=[bool]$request.verify_only
    $book=$books.Open([string]$request.workbook_path,0,$isVerify)
    if($book.ReadOnly -and -not $isVerify){throw 'The working copy opened read-only.'}
    if([int]$book.FileFormat -ne 52){throw 'Expected an XLSM workbook (FileFormat 52).'}
    $excel.Calculation=-4135
    $excel.CalculateBeforeSave=$false
    $sheets=$book.Worksheets
    $probeSheet=$null
    try{$probeSheet=$sheets.Item('Персонал');$result.print_initial=Print-Snapshot $probeSheet}
    finally{Release-Com $probeSheet}
    $result.culture=[string][Globalization.CultureInfo]::CurrentCulture
    if(-not $isVerify){
    $result.active_printer_before=[string]$excel.ActivePrinter
    Restore-PrintAreas $request.print_areas $request.print_profiles
    Write-Stage 'print_commit'
    $excel.PrintCommunication=$true
    $sheet=$sheets.Item('Персонал')
    $result.sheet_name=[string]$sheet.Name
    $result.has_vba=[bool]$book.HasVBProject
    $result.macros_security=[int]$excel.AutomationSecurity
    $result.events_enabled=[bool]$excel.EnableEvents
    Write-Stage 'operations'
    . (Join-Path $PSScriptRoot 'vou_excel_layout.ps1')
    foreach($operation in $request.operations){
        if($operation.type -eq 'set_value' -or $operation.type -eq 'set_formula'){
            $cell=$null
            try{
                $cell=$sheet.Range([string]$operation.address)
                if($operation.type -eq 'set_formula'){$cell.Formula=[string]$operation.formula}
                elseif($operation.value -is [string]){
                    # Literal text: a leading '=' must never execute an Excel formula.
                    $cell.Value2="'"+[string]$operation.value
                }elseif($null -eq $operation.value){$cell.ClearContents()}
                else{$cell.Value2=[double]$operation.value}
            }finally{Release-Com $cell}
        }elseif($operation.type -eq 'insert_rows'){
            $rows=$null;$first=$null;$destination=$null;$prototype=$null
            try{
                $rows=$sheet.Rows
                $first=$rows.Item([int]$operation.before_row)
                $destination=$first.Resize([int]$operation.count)
                [void]$destination.Insert(-4121,0)
                Release-Com $destination;$destination=$null
                Release-Com $first;$first=$null
                $prototypeRow=[int]$operation.prototype_row
                if($prototypeRow -ge [int]$operation.before_row){$prototypeRow += [int]$operation.count}
                $prototype=$rows.Item($prototypeRow)
                $first=$rows.Item([int]$operation.before_row)
                $destination=$first.Resize([int]$operation.count)
                [void]$prototype.Copy()
                [void]$destination.PasteSpecial(-4122)
                $destination.RowHeight=$prototype.RowHeight
                $excel.CutCopyMode=[Enum]::ToObject([Microsoft.Office.Interop.Excel.XlCutCopyMode],0)
            }finally{
                Release-Com $destination;Release-Com $first;Release-Com $prototype;Release-Com $rows
            }
        }else{Invoke-VouLayoutOperation $sheet $excel $operation}
    }
    # Only native formulas on the approved sheet; no Application.Run / VBA execution.
    if($request.calculate_personnel){$sheet.Calculate()}
    $result.print_before_save=Print-Snapshot $sheet
    $savedAreas=@{}
    foreach($property in $request.print_areas.PSObject.Properties){
        $areaSheet=$null;$areaSetup=$null
        try{$areaSheet=$sheets.Item([string]$property.Name);$areaSetup=$areaSheet.PageSetup;$savedAreas[$property.Name]=[string]$areaSetup.PrintArea}
        finally{Release-Com $areaSetup;Release-Com $areaSheet}
    }
    Write-Stage 'save'
    $book.Save()
    Release-Com $sheet;$sheet=$null
    Release-Com $sheets;$sheets=$null
    $book.Close($false)
    Release-Com $book;$book=$null
    # Verify the saved copy can be reopened by Excel, with security still enabled.
    Write-Stage 'reopen'
    $book=$books.Open([string]$request.workbook_path,0,$true)
    $sheets=$book.Worksheets
    }
    $sheet=$sheets.Item('Персонал')
    $result.reopened=$true
    $result.print_reopened_raw=Print-Snapshot $sheet
    # This Excel build imports built-in names incorrectly through COM. Rehydrate
    # only print-area names in memory on EVERY open. Never save the verification
    # session: it must not normalize the restored printer DEVMODE again.
    if($isVerify){$reopenAreas=$request.print_areas}else{$reopenAreas=[pscustomobject]$savedAreas}
    Release-Com $sheet;$sheet=$null
    Restore-PrintAreas $reopenAreas $request.print_profiles
    $result.print_areas_verified=@{}
    foreach($property in $reopenAreas.PSObject.Properties){
        $areaSheet=$null;$areaSetup=$null
        try{
            $areaSheet=$sheets.Item([string]$property.Name);$areaSetup=$areaSheet.PageSetup
            $actual=[string]$areaSetup.PrintArea
            if($actual -ne [string]$property.Value){throw ('Print area verification failed: '+$property.Name)}
            $result.print_areas_verified[$property.Name]=$actual
        }finally{Release-Com $areaSetup;Release-Com $areaSheet}
    }
    $sheet=$sheets.Item('Персонал')
    $result.print_reopened=Print-Snapshot $sheet
    $result.readback=@{}
    foreach($address in $request.readback){
        $cell=$null
        try{
            $cell=$sheet.Range([string]$address)
            $result.readback[[string]$address]=@{value=$cell.Value2;formula=$cell.Formula}
        }finally{Release-Com $cell}
    }
    $result.readback_blocks=@{}
    foreach($address in $request.readback_ranges){
        $block=$null
        try{
            $block=$sheet.Range([string]$address)
            $values=$block.Value2
            $grid=@()
            for($r=1;$r -le $values.GetLength(0);$r++){
                $line=@()
                for($c=1;$c -le $values.GetLength(1);$c++){$line+=,$values[$r,$c]}
                $grid+=,@($line)
            }
            $result.readback_blocks[[string]$address]=@($grid)
        }finally{Release-Com $block}
    }
    $sheet.Activate()
    Set-OwnedExcelPrinter ([string]$request.print_profiles.('Персонал'))
    $pageSetup=$null
    try{$pageSetup=$sheet.PageSetup;$result.print_area=[string]$pageSetup.PrintArea;$result.print_communication=[bool]$excel.PrintCommunication;$result.pdf_setup=@{paper_size=[int]$pageSetup.PaperSize;orientation=[int]$pageSetup.Orientation;zoom=$pageSetup.Zoom;fit_wide=$pageSetup.FitToPagesWide;fit_high=$pageSetup.FitToPagesTall;active_printer=[string]$excel.ActivePrinter}}
    finally{Release-Com $pageSetup}
    if($request.pdf_path){
        if(-not $isVerify){throw 'PDF export is allowed only in the read-only verification session.'}
        Write-Stage 'export_pdf'
        # Installed Adobe PDF reports A4 to COM but exports a 900 x 636 mm page.
        # Use Microsoft's installed virtual driver ONLY in this unsaved session;
        # the workbook retains all four original printer profiles byte-for-byte.
        Set-OwnedExcelPrinter 'Microsoft Print to PDF'
        $pdfSetup=$null
        try{
            $pdfSetup=$sheet.PageSetup
            # Approved fingerprinted template: paperSize=9, landscape, fit width=1.
            $pdfSetup.PaperSize=[Enum]::ToObject([Microsoft.Office.Interop.Excel.XlPaperSize],9)
            if([int]$pdfSetup.Orientation -ne 2 -or $pdfSetup.FitToPagesWide -ne 1){throw 'Unexpected PDF page layout'}
            if([string]$pdfSetup.PrintArea -ne [string]$reopenAreas.('Персонал')){throw 'PDF print area was lost'}
            $result.pdf_setup=@{paper_size=[int]$pdfSetup.PaperSize;orientation=[int]$pdfSetup.Orientation;
                fit_wide=$pdfSetup.FitToPagesWide;fit_high=$pdfSetup.FitToPagesTall;zoom=$pdfSetup.Zoom;
                active_printer=[string]$excel.ActivePrinter;area=[string]$pdfSetup.PrintArea}
        }finally{Release-Com $pdfSetup}
        $sheet.ExportAsFixedFormat(0,[string]$request.pdf_path,0,$true,$false)
        $result.pdf_path=[string]$request.pdf_path
    }
    $result.ok=$true
}catch{
    $result.error=$_.Exception.Message
}finally{
    Release-Com $sheet;Release-Com $sheets
    if($null -ne $book){try{$book.Close($false)}catch{};Release-Com $book}
    Release-Com $books
    if($null -ne $excel -and $ownsExcel){try{$excel.Quit()}catch{}}
    Release-Com $excel
    $sheet=$null;$sheets=$null;$book=$null;$books=$null;$excel=$null
    [GC]::Collect();[GC]::WaitForPendingFinalizers()
    if($ownsExcel){
        for($attempt=0;$attempt -lt 50;$attempt++){
            if(-not (Get-Process -Id $excelOwnerProcessId -ErrorAction SilentlyContinue)){break}
            Start-Sleep -Milliseconds 100
        }
        $remaining=Get-Process -Id $excelOwnerProcessId -ErrorAction SilentlyContinue
        if($remaining -and $remaining.ProcessName -eq 'EXCEL' -and $remaining.StartTime.ToUniversalTime().Ticks -eq $excelStartTicks){
            Stop-Process -Id $excelOwnerProcessId -Force
            $result.forced_cleanup=$true
            for($exitAttempt=0;$exitAttempt -lt 30;$exitAttempt++){
                if(-not (Get-Process -Id $excelOwnerProcessId -ErrorAction SilentlyContinue)){break}
                Start-Sleep -Milliseconds 100
            }
        }
        $result.excel_process_exited=$null -eq (Get-Process -Id $excelOwnerProcessId -ErrorAction SilentlyContinue)
    }
    Write-JsonFile $request.result_path $result
}
if(-not $result.ok){exit 1}
