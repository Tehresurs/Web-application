import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi import HTTPException
from app.services.vou_archive import VouArchive
from app.api import vou_archive as api


class VouArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.archive = VouArchive(self.output/'archive',self.output)
        self.source = self.output/'test.xlsm'
        # Storage fixture only: not a real Excel result or a user report.
        with ZipFile(self.source,'w') as book:
            book.writestr('xl/workbook.xml','<workbook/>')
            book.writestr('xl/vbaProject.bin',b'test fixture')
        self.data = dict(year=2026,month=10,total_cents=12400,sections=[dict(total_cents=12400)])
        self.settings = dict(contract_number='TEST',contract_date='2026-10-18',contract_revision='2',
                             customer_signer_name='TEST CUSTOMER',contractor_signer_name='TEST CONTRACTOR')
        self.checks = dict(excel_reopened=True,preservation_accepted=True,data_totals_match=True)

    def publish(self):
        return self.archive.publish(self.source,data=self.data,settings=self.settings,verification=self.checks)

    def test_repeat_creates_separate_files_and_snapshots_do_not_follow_settings(self):
        first = self.publish()
        self.settings['contract_number']='NEW'
        second = self.publish()
        self.assertNotEqual(first['id'],second['id'])
        old,path=self.archive.read(first['id'])
        new,_=self.archive.read(second['id'])
        self.assertEqual(old['settings']['contract_number'],'TEST')
        self.assertEqual(new['settings']['contract_number'],'NEW')
        self.assertEqual(path.read_bytes(),self.source.read_bytes())
        self.assertEqual(len(self.archive.list_reports()['items']),2)
        self.assertEqual(old['data']['total_cents'],12400)

    def test_incomplete_requisites_or_checks_are_never_published(self):
        self.settings['customer_signer_name']=''
        with self.assertRaises(ValueError):self.publish()
        self.settings['customer_signer_name']='TEST'
        self.checks['excel_reopened']=False
        with self.assertRaises(ValueError):self.publish()
        self.assertFalse(self.archive.root.exists())

    def test_tampered_workbook_is_not_downloaded_or_silently_listed(self):
        item=self.publish()
        _,path=self.archive.read(item['id'])
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.archive.read(item['id'])
        listed=self.archive.list_reports()
        self.assertEqual(listed['items'],[])
        self.assertEqual(len(listed['warnings']),1)
        with patch.object(api,'archive',self.archive):
            with self.assertRaises(HTTPException) as error:api.report_file(item['id'])
            self.assertEqual(error.exception.status_code,409)

    def test_invalid_ids_and_republishing_archive_are_rejected(self):
        for report_id in ('../test','A'*32,'','x'*32):
            with self.assertRaises(ValueError):self.archive.read(report_id)
        item=self.publish()
        _,path=self.archive.read(item['id'])
        with self.assertRaises(ValueError):
            self.archive.publish(path,data=self.data,settings=self.settings,verification=self.checks)

    def test_partial_publish_is_cleaned_and_not_visible(self):
        with patch('app.services.vou_archive.shutil.copyfileobj',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.publish()
        self.assertEqual(list(self.archive.root.iterdir()),[])
        self.assertEqual(self.archive.list_reports()['items'],[])

    def test_parallel_publish_never_overwrites_an_existing_report(self):
        with ThreadPoolExecutor(max_workers=3) as executor:
            reports=list(executor.map(lambda _:self.publish(),range(3)))
        self.assertEqual(len({r['id'] for r in reports}),3)
        self.assertEqual(len(self.archive.list_reports()['items']),3)
        for item in reports:self.archive.read(item['id'])

    def test_api_returns_file_and_full_frozen_metadata(self):
        item=self.publish()
        with patch.object(api,'archive',self.archive):
            response=api.report_file(item['id'])
            self.assertEqual(response.filename,item['filename'])
            self.assertEqual(api.report_metadata(item['id'])['item']['settings'],self.settings)
            self.assertEqual(len(api.reports()['items']),1)
            with self.assertRaises(HTTPException) as error:api.report_file('0'*32)
            self.assertEqual(error.exception.status_code,404)

    def test_bad_total_and_invalid_source_are_rejected(self):
        self.data['total_cents']=1
        with self.assertRaises(ValueError):self.publish()
        self.data['total_cents']=12400
        self.source.write_bytes(b'not a workbook')
        with self.assertRaises(ValueError):self.publish()
        self.assertFalse(self.archive.root.exists())


    def test_technical_workbook_cannot_be_published(self):
        self.checks['technical_only']=True
        with self.assertRaisesRegex(ValueError,'Технические'):self.publish()
        self.assertFalse(self.archive.root.exists())
