from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from app.services.vou_data import prepare_data
from app.services.vou_layout import build_plan,column
from app.services.vou_excel_com import validate_operations
from app.services.vou_dk_display import empty_dk_rows
from app.services import vou_report
from test_vou_data import inputs,cell


def requisites():
    return dict(contract_number='TEST',contract_date='2026-10-18',contract_revision='2',
                customer_signer_name='TEST CUSTOMER',contractor_signer_name='TEST CONTRACTOR')


def native_rows(args):
    for employee in args[0]['employees']:
        employee['position_name']=next(p['name'] for p in args[1] if p['id']==employee['position_id'])
        for row in employee['rows']:
            item=next(iter(row['cells'].values()))
            row['row_key']=f"{employee['employee_id']}:OBJECT:{item['object_id']}"
    return args


class VouReportTests(unittest.TestCase):
    def test_numbering_restarts_in_each_section_and_follows_subsections(self):
        data=prepare_data(*inputs([cell(fid=1,obj=1,category=1),cell(fid=2,obj=2,category=1),
                                  cell(fid=3,obj=3,category=2),cell(fid=4,obj=4,category=7)],pid=7))
        plan=build_plan(data,requisites())
        labels=[plan['expected']['B'+str(r['row'])] for r in plan['rows']]
        self.assertEqual(labels,['1.1','1.2','2.1','6.1.1'])
        self.assertEqual(plan['expected']['B'+str(plan['headers']['1'])],'1.')
        self.assertEqual(plan['expected']['B'+str(plan['headers']['6'])],'6.')
        self.assertEqual(data['total_cents'],400)

    def test_month_lengths_and_blank_surplus_dates(self):
        for year,month,length in [(2026,2,28),(2028,2,29),(2026,4,30),(2026,10,31)]:
            args=inputs([cell(day=f'{year}-{month:02d}-01',share=50)])
            args[0].update(year=year,month=month)
            data=prepare_data(*args)
            plan=build_plan(data,requisites())
            validate_operations(plan['operations'])
            self.assertIsNotNone(plan['expected'][column(length+5)+'13'])
            for d in range(length+1,32):self.assertIsNone(plan['expected'][column(d+5)+'13'])
            for values in plan['values']:self.assertIsNone(values[-1])
            row=plan['rows'][0]
            self.assertEqual(plan['values'][row['row']-14][4],0.5)
            self.assertIsNone(plan['values'][row['row']-14][5])

    def test_dynamic_growth_preserves_next_section_and_signatures(self):
        data=prepare_data(*inputs([cell(fid=i+1,obj=i+1,category=2,share=1) for i in range(80)]))
        plan=build_plan(data,requisites())
        self.assertTrue(any(op['type']=='insert_rows' for op in plan['operations']))
        second=[r['row'] for r in plan['rows'] if r['category_id']==2]
        self.assertEqual(len(second),80)
        self.assertLess(max(second),plan['headers']['3'])
        self.assertEqual(plan['signature_row'],plan['grand_row']+11)
        self.assertEqual(plan['expected']['AK'+str(plan['grand_row'])],0.8)
        validate_operations(plan['operations'])

    def test_dk_only_objects_have_empty_daily_cells_and_no_added_time(self):
        cells=[cell(fid=i+1,obj=i+1,category=2,share=0,is_dk=True,excluded_from_production=True) for i in range(3)]
        args=native_rows(inputs(cells));data=prepare_data(*args);original=deepcopy(data)
        display,controls=empty_dk_rows(data,dict(matrix=args[0],positions=args[1]))
        self.assertEqual(len(controls),3)
        self.assertEqual(display['total_cents'],0)
        self.assertEqual(data,original)
        plan=build_plan(display,requisites())
        self.assertEqual(len(plan['rows']),3)
        for r in plan['rows']:
            self.assertTrue(all(v is None for v in plan['values'][r['row']-14][4:35]))
        self.assertEqual(len(plan['subheaders']),4)

    def test_dk_other_dates_and_original_values_are_preserved(self):
        args=inputs([cell(fid=1,day='2026-10-01',category=2,share=50),
                     cell(fid=2,day='2026-10-02',category=2,share=0,is_dk=True)])
        args=native_rows(args)
        data=prepare_data(*args)
        display,controls=empty_dk_rows(data,dict(matrix=args[0],positions=args[1]))
        self.assertEqual(display['total_cents'],50)
        self.assertEqual(len(display['sections'][1]['rows']),1)
        row=display['sections'][1]['rows'][0]
        self.assertEqual(row['days_cents']['2026-10-01'],50)
        self.assertEqual(row['days_cents']['2026-10-02'],0)
        self.assertEqual(len(controls),1)

    def test_incomplete_user_settings_block_excel_and_archive(self):
        with patch.object(vou_report.vou_settings,'get_settings',return_value={}), \
             patch.object(vou_report.vou_data,'prepare_month') as prepare, \
             patch.object(vou_report,'render') as render, \
             patch.object(vou_report,'VouArchive') as archive:
            with self.assertRaisesRegex(ValueError,'Заполните реквизиты'):vou_report.generate(2026,10)
            prepare.assert_not_called();render.assert_not_called();archive.assert_not_called()

    def test_generate_archives_the_exact_settings_snapshot_after_verification(self):
        data=prepare_data(*inputs([cell()]))
        saved=requisites();context={'matrix':{},'positions':[]}
        checks=dict(excel_reopened=True,preservation_accepted=True,data_totals_match=True)
        with patch.object(vou_report.vou_settings,'get_settings',return_value=saved), \
             patch.object(vou_report.vou_data,'prepare_month',return_value=(data,context)), \
             patch.object(vou_report,'render',return_value=(Path('report.xlsm'),Path('report.pdf'),checks)) as render, \
             patch.object(vou_report,'VouArchive') as archive:
            archive.return_value.publish.return_value={'id':'test'}
            result=vou_report.generate(2026,10)
            self.assertEqual(result['item']['id'],'test')
            self.assertEqual(archive.return_value.publish.call_args.kwargs['settings'],saved)
            render.assert_called_once_with(data,saved,context=context)

    def test_invalid_shift_write_or_arbitrary_formula_is_rejected(self):
        for op in [dict(type='set_block',address='B14',values=[[None]*36+[1]]),
                   dict(type='set_formula',address='AL15',formula='=SUM(AL16:AL17)'),
                   dict(type='set_formula',address='AK15',formula='=WEBSERVICE("x")'),
                   dict(type='delete_rows',before_row=1,count=2)]:
            with self.assertRaises(ValueError):validate_operations([op])
