import unittest
from datetime import date
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile
from openpyxl import load_workbook
from app.api.deployment import export
from test_deployment import DeploymentTests


class AnalysisExportTests(unittest.TestCase):
    def test_default_does_not_load_analysis_and_opt_in_keeps_report_identical(self):
        report=DeploymentTests().report()
        staff=dict(position_name='=Untrusted',planned=7,actual=3,deviation=-4,completeness=42.86)
        point=dict(date='2026-10-15',staffing=[staff],staffing_total=staff,
                   production=dict(total=3,reports=None,average=None,source='FACT'),
                   warnings=[dict(code='DOCUMENT_IDENTITY_UNAVAILABLE',employee_id=1)])
        data=dict(**point,history=[{**point,'date':'2026-10-14'}],limitations=['Existing limitation'])
        with patch('app.api.deployment.get_report',return_value=report), \
             patch('app.api.deployment.get_analysis',return_value=data) as analysis:
            plain=export(date(2026,10,15)).body
            analysis.assert_not_called()
            extended=export(date(2026,10,15),include_analysis=True).body
            analysis.assert_called_once_with(date(2026,10,15))
        first=load_workbook(BytesIO(plain));second=load_workbook(BytesIO(extended))
        self.assertEqual(len(first.sheetnames),1)
        self.assertEqual(len(second.sheetnames),2)
        with ZipFile(BytesIO(plain)) as a, ZipFile(BytesIO(extended)) as b:
            self.assertEqual(a.read('xl/worksheets/sheet1.xml'),b.read('xl/worksheets/sheet1.xml'))
        sheet=second.worksheets[1]
        self.assertEqual(sheet['A4'].value,'=Untrusted')
        self.assertEqual(sheet['A4'].data_type,'s')
        self.assertEqual(sheet['E4'].value,42.86)
        self.assertFalse(any(c.data_type=='f' for row in sheet for c in row))
        self.assertIn('Existing limitation',[c.value for row in sheet for c in row])
        self.assertIn('DOCUMENT_IDENTITY_UNAVAILABLE',[c.value for row in sheet for c in row])
