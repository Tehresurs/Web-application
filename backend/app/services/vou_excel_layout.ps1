# Additive B3 layout operations. Lifecycle/security/save/reopen remain in B1 worker.
function Invoke-VouLayoutOperation($sheet,$excel,$op){
    $range=$null;$source=$null;$rows=$null;$setup=$null
    try{
        switch([string]$op.type){
            'delete_rows' {
                $rows=$sheet.Rows
                $range=$rows.Item([int]$op.before_row).Resize([int]$op.count)
                [void]$range.Delete(-4162)
            }
            'clear_range' {$range=$sheet.Range([string]$op.address);$range.ClearContents()}
            'set_block' {
                $height=$op.values.Count;$width=$op.values[0].Count
                $array=New-Object 'object[,]' $height,$width
                for($r=0;$r -lt $height;$r++){
                    for($c=0;$c -lt $width;$c++){
                        $value=$op.values[$r][$c]
                        if($value -is [string]){$array[$r,$c]="'"+$value}
                        elseif($null -ne $value){$array[$r,$c]=[double]$value}
                    }
                }
                $source=$sheet.Range([string]$op.address)
                $range=$source.Resize($height,$width)
                $range.Value2=$array
            }
            'copy_row_format' {
                $source=$sheet.Range(('B'+$op.source_row+':AL'+$op.source_row))
                $range=$sheet.Range(('B'+$op.target_row+':AL'+$op.target_row))
                [void]$source.Copy();[void]$range.PasteSpecial(-4122)
                $range.RowHeight=$source.RowHeight
                $excel.CutCopyMode=[Enum]::ToObject([Microsoft.Office.Interop.Excel.XlCutCopyMode],0)
            }
            'autofit_rows' {
                $source=$sheet.Range(('B'+$op.first_row+':B'+$op.last_row))
                $source.WrapText=$false
                $source.ShrinkToFit=$true
                $range=$sheet.Range(('B'+$op.first_row+':AK'+$op.last_row))
                $rows=$range.Rows
                [void]$rows.AutoFit()
            }
            'fit_signatures' {
                $range=$sheet.Range(('AE'+$op.row+':AK'+$op.row))
                $range.WrapText=$true
                $range.RowHeight=[Math]::Max([double]$range.RowHeight,36)
            }
            'fit_header' {
                $rows=$sheet.Rows
                $range=$rows.Item(12)
                $range.RowHeight=[Math]::Max([double]$range.RowHeight,45)
            }
            'print_end' {
                $setup=$sheet.PageSetup
                $setup.PrintArea=('$A$1:$AL$'+$op.row)
            }
            default {throw 'Unsupported workbook layout operation.'}
        }
    }finally{Release-Com $range;Release-Com $source;Release-Com $rows;Release-Com $setup}
}
