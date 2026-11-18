from io import BytesIO
from hashlib import sha256
import unittest
from openpyxl import load_workbook
from app.services.luvr_export import DEFAULT_TEMPLATE
from app.services.luvr_export_table import render_table
from app.services.luvr_export_footer import fill_footer,footer_values
from app.services.luvr_export_layout import compact_month
from test_luvr_export_footer import complete_snapshot
from test_luvr_export_table import data_set


class CompactTests(unittest.TestCase):
    def check_count(self,n):
        before=sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest()
        snapshot=complete_snapshot()
        original=fill_footer(render_table(snapshot,data_set(n)),footer_values(snapshot))
        source=load_workbook(BytesIO(original)).active
        result=compact_month(original,n)
        sheet=load_workbook(BytesIO(result)).active
        cached=load_workbook(BytesIO(result),data_only=True).active
        offset=76-n;total=9+n
        self.assertEqual(sheet.cell(total-1,1).value,n)
        self.assertEqual(sheet.cell(total,37).value,f'=SUM(AK9:AK{total-1})')
        self.assertEqual(cached.cell(total,37).value,n*3)
        for row in source:
            for cell in row:
                if total<=cell.row<85:continue
                target=sheet.cell(cell.row-offset if cell.row>=85 else cell.row,cell.column)
                self.assertEqual(cell._style,target._style)
                if cell.row==85 and 6<=cell.column<=39:
                    self.assertEqual(cell.value,cached.cell(total,cell.column).value)
                elif cell.data_type!='f':self.assertEqual(cell.value,target.value)
        for old_row in range(85,102):
            self.assertEqual(source.row_dimensions[old_row].height,sheet.row_dimensions[old_row-offset].height)
        self.assertEqual(sheet['A'+str(total+5)].value.strip(),'Разработал')
        self.assertEqual(sheet['A'+str(total+8)].value.strip(),'Согласовано')
        self.assertEqual(sheet['A'+str(total+16)].value,'(Уволен) - увольнение сотрудника')
        self.assertEqual(str(sheet.print_area),str(source.print_area).replace('$101','$'+str(101-offset)))
        self.assertEqual(str(sheet.merged_cells),str(source.merged_cells))
        for key,value in source.column_dimensions.items():self.assertEqual(dict(value),dict(sheet.column_dimensions[key]))
        self.assertEqual(sheet.max_row,101-offset)
        formula=sheet.cell(total+2,37).value
        self.assertTrue(formula.startswith('=AK'+str(total)+'-'))
        self.assertNotIn('#REF!',formula)
        if n==1:self.assertEqual(formula,'=AK10-0-0-0-0-2')
        self.assertEqual(before,sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest())

    def test_one(self):self.check_count(1)
    def test_65(self):self.check_count(65)
    def test_67(self):self.check_count(67)
    def test_76(self):self.check_count(76)
