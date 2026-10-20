"""B2 projection tests: input shares are already calculated by the matrix."""
from copy import deepcopy
import unittest
from app.services.vou_data import prepare_data, select_matrix_cells, VouDataError


def catalogs():
    return ([dict(id=i, name=f"Должность {i}", aos_description="Описание") for i in (2,3,4,5,7,9,10,11,12,13,15,16,17)],
            [dict(id=i, name=f"Категория {i}", parent_id=6 if i>6 else None,
                  sort_order=i-6 if i>6 else i) for i in range(1,10)])


def cell(fid=1, day="2026-10-01", category=1, share=100, obj=1, **extra):
    return dict(date=day, employee_id=1, source="FACT", report_received=True,
                source_fact_id=fid, kind="OBJECT", category_id=category, share_cents=share,
                object_id=obj, object_name=f"Объект {obj}", **extra)


def inputs(cells, pid=2):
    # Separate display lanes may contain the same object; group FACT cells once.
    matrix=dict(year=2026, month=10, formed=True, employees=[dict(employee_id=1,
        position_id=pid, full_name="Иванов Иван", rows=[dict(source="MIXED", total_cents=999999,
        cells={c["date"]:c}) for c in cells])])
    facts=[dict(id=c["source_fact_id"], employee_id=c["employee_id"],
        report_date=c["date"], category_id=c["category_id"]) for c in cells if c["source"]=="FACT"]
    positions,categories=catalogs()
    return matrix, positions, categories, facts


class VouDataTests(unittest.TestCase):
    def test_multiple_objects_keep_existing_shares_and_no_monthly_total(self):
        args=inputs([cell(share=33),cell(fid=2,share=67,obj=2)])
        before=deepcopy(args);r=prepare_data(*args)
        self.assertEqual(r["total_cents"],100)
        self.assertEqual([x["total_cents"] for x in r["sections"][0]["rows"]],[33,67])
        self.assertEqual(args,before)

    def test_two_sources_same_object_are_aggregated_once(self):
        r=prepare_data(*inputs([cell(share=25),cell(fid=2,share=25)]))
        rows=r["sections"][0]["rows"]
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]["total_cents"],50)
        self.assertEqual(len(rows[0]["sources"]),2)

    def test_duplicate_fact_is_blocked_not_summed(self):
        with self.assertRaises(VouDataError) as e:prepare_data(*inputs([cell(),cell()]))
        self.assertEqual(e.exception.code,"DUPLICATE_MATRIX_FACT")

    def test_category_changes_are_taken_from_dated_cells(self):
        r=prepare_data(*inputs([cell(category=1,share=50),cell(fid=2,day="2026-10-02",category=2)]))
        self.assertEqual(r["sections"][0]["days_cents"]["2026-10-01"],50)
        self.assertEqual(r["sections"][1]["days_cents"]["2026-10-02"],100)
        self.assertEqual(r["total_cents"],150)

    def test_existing_dated_category_override_is_preserved(self):
        args=list(inputs([cell(category=2,applied_overrides={"CATEGORY":55})]))
        args[3][0]["category_id"]=1
        r=prepare_data(*args)
        self.assertEqual(r["sections"][1]["total_cents"],100)
        self.assertEqual(r["sections"][1]["rows"][0]["sources"][0]["confirmed_category_id"],1)
        args[0]["employees"][0]["rows"][0]["cells"]["2026-10-01"]["applied_overrides"]={}
        with self.assertRaises(VouDataError):prepare_data(*args)

    def test_dk_and_excluded_from_production(self):
        for flag in ("is_dk","excluded_from_production"):
            r=prepare_data(*inputs([cell(share=0,**{flag:True})]))
            self.assertEqual(r["total_cents"],0)
            self.assertEqual(r["counts"]["excluded_dk"],1)
            self.assertEqual(r["sections"][0]["rows"],[])

    def test_plan_fills_missing_fact_in_mixed_row(self):
        c=cell(day="2026-10-02");c.update(source="PLAN",report_received=False,source_fact_id=None)
        args=list(inputs([cell(share=50),c]))
        args[0]["employees"][0]["rows"]=[dict(source="MIXED",total_cents=150,
            cells={"2026-10-01":cell(share=50),"2026-10-02":c})]
        r=prepare_data(*args)
        self.assertEqual(r["total_cents"],150);self.assertEqual(r["control_cents"]["included_PLAN"],100)

    def test_description_missing_is_warning_no_fallback(self):
        args=list(inputs([cell()]));args[1][0]["aos_description"]="   "
        r=prepare_data(*args)
        self.assertIsNone(r["sections"][0]["rows"][0]["aos_description"])
        self.assertTrue(any(w["code"]=="MISSING_AOS_DESCRIPTION" for w in r["warnings"]))

    def test_excluded_position_never_enters_totals(self):
        r=prepare_data(*inputs([cell()],pid=17))
        self.assertEqual(r["total_cents"],0);self.assertEqual(r["control_cents"]["excluded_position"],100)

    def test_six_sections_and_four_empty_subsections_no_shifts(self):
        r=prepare_data(*inputs([]))
        self.assertEqual(len(r["sections"]),6)
        self.assertEqual([s["code"] for s in r["sections"][5]["subsections"]],["6.1","6.2","6.3","6.4"])
        self.assertTrue(all(s["total_cents"]==0 for s in r["sections"]))
        self.assertEqual(r["total_cents"],0)
        self.assertNotIn("AL",r);self.assertNotIn("shifts",r)

    def test_missing_6_4_never_creates_or_remaps_category(self):
        args=inputs([cell(category=6)])
        before=deepcopy(args[2])
        r=prepare_data(*args)
        self.assertEqual(r['total_cents'],0)
        self.assertEqual(r['control_cents']['excluded_unmapped_category'],100)
        self.assertTrue(any(w['code']=='OBJECT_CATEGORY_MISSING_OR_UNMAPPED' for w in r['warnings']))
        self.assertEqual(args[2],before)

    def test_existing_fourth_subcategory_uses_database_id(self):
        args=list(inputs([cell(category=42)],pid=16))
        args[2].append(dict(id=42,name="Имя не используется для сопоставления",parent_id=6,sort_order=4))
        r=prepare_data(*args)
        self.assertEqual(r["sections"][5]["subsections"][3]["category_id"],42)
        self.assertEqual(r["sections"][5]["total_cents"],100)
        self.assertEqual(r["total_cents"],100)

    def test_unagreed_position_order_blocks_real_case(self):
        with self.assertRaises(VouDataError) as e:prepare_data(*inputs([cell(category=4)],pid=10))
        self.assertEqual(e.exception.code,"POSITION_ORDER_NOT_AGREED")

    def test_position_order_fio_and_employee_objects_stay_together(self):
        args=list(inputs([cell(obj=2),cell(fid=2,day="2026-10-02",obj=3)]))
        other=deepcopy(args[0]["employees"][0]);other.update(employee_id=2,full_name="Аюпов Альберт")
        other["rows"]=[dict(cells={"2026-10-01":cell(fid=3,obj=1)})]
        other["rows"][0]["cells"]["2026-10-01"]["employee_id"]=2
        args[0]["employees"].append(other)
        args[3].append(dict(id=3,employee_id=2,report_date="2026-10-01",category_id=1))
        r=prepare_data(*args)
        self.assertEqual([x["employee_id"] for x in r["sections"][0]["rows"]],[2,1,1])
        args[0]["employees"][0]["position_id"]=3
        r=prepare_data(*args)
        self.assertEqual([x["position_id"] for x in r["sections"][0]["rows"]],[2,3,3])

    def test_calendar_months(self):
        for year,month,days in [(2025,2,28),(2024,2,29),(2026,4,30),(2026,10,31)]:
            args=list(inputs([]));args[0].update(year=year,month=month)
            self.assertEqual(len(prepare_data(*args)["days_cents"]),days)

    def test_unconfirmed_fact_and_unformed_month_are_blocked(self):
        args=list(inputs([cell()]));args[3]=[]
        with self.assertRaises(VouDataError):prepare_data(*args)
        args=list(inputs([]));args[0]["formed"]=False
        with self.assertRaises(VouDataError):prepare_data(*args)


class PriorityTests(unittest.TestCase):
    def plan(self, **values):
        c=cell(**values);c.update(source="PLAN",report_received=False,assignment_item_id=90)
        return c

    def test_fact_wins_over_plan_for_same_allocation_even_if_category_changes(self):
        for reverse in (False,True):
            cells=[cell(share=25),self.plan(share=100,category=2)]
            if reverse:cells.reverse()
            r=prepare_data(*inputs(cells))
            self.assertEqual(r["total_cents"],25)
            self.assertEqual(r["sections"][1]["total_cents"],0)
            self.assertEqual(r["control_cents"]["superseded_plan"],100)

    def test_plan_for_other_object_is_not_suppressed_by_fact(self):
        r=prepare_data(*inputs([cell(share=50),self.plan(obj=2,share=50)]))
        self.assertEqual(r["total_cents"],100)
        self.assertEqual(r["control_cents"]["included_FACT"],50)
        self.assertEqual(r["control_cents"]["included_PLAN"],50)

    def test_zero_fact_still_supersedes_plan(self):
        r=prepare_data(*inputs([cell(share=0),self.plan(share=100)]))
        self.assertEqual(r["total_cents"],0)
        self.assertNotIn("included_PLAN",r["control_cents"])

    def test_dk_fact_does_not_fall_back_to_plan(self):
        r=prepare_data(*inputs([cell(share=0,is_dk=True),self.plan(share=100)]))
        self.assertEqual(r["total_cents"],0)
        self.assertEqual(r["counts"]["excluded_dk"],1)

    def test_plan_dk_and_sl_are_excluded(self):
        for pid,flag in [(2,{"is_dk":True}),(2,{"excluded_from_production":True}),(17,{})]:
            self.assertEqual(prepare_data(*inputs([self.plan(**flag)],pid=pid))["total_cents"],0)

    def test_separate_native_matrix_lanes_preserved(self):
        args=list(inputs([cell(share=50),self.plan(share=50)]))
        for i,row in enumerate(args[0]["employees"][0]["rows"]):row["row_key"]=f"lane-{i}"
        r=prepare_data(*args)
        self.assertEqual(len(r["sections"][0]["rows"]),2)
        self.assertEqual(r["total_cents"],100)

    def test_duplicate_plan_is_error(self):
        with self.assertRaises(VouDataError) as e:prepare_data(*inputs([self.plan(),self.plan()]))
        self.assertEqual(e.exception.code,"DUPLICATE_MATRIX_PLAN")

    def test_cameral_is_report_only_subsection_6_4(self):
        c=self.plan(category=None);c.update(kind='CAMERAL',object_id=None,object_name=None)
        args=inputs([c],pid=11);before=deepcopy(args)
        r=prepare_data(*args)
        self.assertEqual(r['sections'][5]['subsections'][3]['total_cents'],100)
        self.assertEqual(r['sections'][5]['total_cents'],100)
        self.assertEqual(r['total_cents'],100)
        self.assertIsNone(r['sections'][5]['subsections'][3]['rows'][0]['category_id'])
        self.assertEqual(args,before)

    def test_object_plan_without_category_is_diagnostic_exclusion(self):
        r=prepare_data(*inputs([self.plan(category=None,share=50)]))
        self.assertEqual(r['total_cents'],0)
        warning=next(w for w in r['warnings'] if w['code']=='OBJECT_CATEGORY_MISSING_OR_UNMAPPED')
        self.assertEqual((warning['full_name'],warning['date'],warning['object_name'],warning['share_cents']),
                         ('Иванов Иван','2026-10-01','Объект 1',50))

    def test_plan_provenance_is_not_marked_as_received_fact(self):
        r=prepare_data(*inputs([self.plan()]))
        provenance=r["sections"][0]["rows"][0]["sources"][0]
        self.assertEqual(provenance["source"],"PLAN")
        self.assertIsNone(provenance["fact_id"])
        self.assertEqual(provenance["assignment_item_id"],90)


class VouConnectionTests(unittest.TestCase):
    def test_wrong_database_is_blocked_before_matrix_calculation(self):
        from unittest.mock import MagicMock,patch
        from app.services.vou_data import prepare_month
        conn=MagicMock();conn.execute.return_value.fetchone.return_value=('ai_excel_agent','public')
        with patch('app.database.db.get_connection') as connection,patch('app.services.production_matrix.calculate_month') as calculate:
            connection.return_value.__enter__.return_value=conn
            with self.assertRaises(VouDataError) as error:prepare_month(2026,10)
            self.assertEqual(error.exception.code,'VOU_WRONG_DATABASE_PROFILE')
            calculate.assert_not_called()

    def test_matrix_and_directories_use_the_same_checked_snapshot(self):
        from unittest.mock import MagicMock,patch
        from app.services.vou_data import prepare_month
        conn=MagicMock();conn.execute.return_value.fetchone.return_value=('ai_excel_agent_test','test_construction_identity_stage46')
        positions,categories=catalogs();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect=[positions,[{'id':100,'position_id':2,'definition':{'name':'Historical position','aos_description':'Historical AOS'}}],categories,[]]
        with patch('app.database.db.get_connection') as connection,patch('app.services.production_matrix.calculate_month',return_value=inputs([])[0]) as calculate:
            connection.return_value.__enter__.return_value=conn
            result=prepare_month(2026,10)
            calculate.assert_called_once_with(2026,10,connection=conn)
            self.assertEqual(result['total_cents'],0)
            self.assertIn('READ ONLY',conn.execute.call_args_list[0].args[0])
            self.assertTrue(any('personnel_position_definitions' in call.args[0] for call in cur.execute.call_args_list))


class ApprovedSubsectionOrderTests(unittest.TestCase):
    def test_existing_order_is_unchanged_and_additions_are_scoped(self):
        from app.services.vou_data import position_order, OTHER_POSITION_ORDER, MAIN_POSITION_ORDER
        self.assertEqual(position_order('6.2'), OTHER_POSITION_ORDER + (3,))
        self.assertEqual(position_order('6.4'), OTHER_POSITION_ORDER + (6,8,14,20))
        self.assertEqual(position_order('6.1'), OTHER_POSITION_ORDER)
        self.assertEqual(position_order('6.3'), OTHER_POSITION_ORDER)
        self.assertEqual(position_order('1'), MAIN_POSITION_ORDER)
        args=inputs([cell(category=7)],pid=3)
        with self.assertRaises(VouDataError) as error:prepare_data(*args)
        self.assertEqual(error.exception.code,'POSITION_ORDER_NOT_AGREED')
        self.assertEqual(error.exception.details['subsection'],'6.1')

    def test_additional_positions_keep_values_and_sort_by_position_then_fio(self):
        matrix=dict(year=2026,month=10,formed=True,employees=[])
        positions,categories=catalogs()
        for pid in (6,8,14,20):positions.append(dict(id=pid,name=f'Должность {pid}',aos_description=None))
        for eid,(pid,fio) in enumerate([(20,'Яковлев'),(14,'Иванов'),(8,'Петров'),(6,'Яковлев'),(6,'Андреев'),(11,'Сидоров'),(3,'Борисов')],1):
            c=cell(category=8 if pid==3 else None)
            c.update(employee_id=eid,source='PLAN',report_received=False,assignment_item_id=eid)
            if pid!=3:c.update(kind='CAMERAL',object_id=None,object_name=None)
            matrix['employees'].append(dict(employee_id=eid,position_id=pid,full_name=fio,
                                           rows=[dict(cells={c['date']:c})]))
        before=deepcopy((matrix,positions,categories))
        result=prepare_data(matrix,positions,categories,[])
        subs=result['sections'][5]['subsections']
        self.assertEqual(subs[1]['total_cents'],100)
        self.assertEqual([r['position_id'] for r in subs[1]['rows']],[3])
        self.assertEqual([r['position_id'] for r in subs[3]['rows']],[11,6,6,8,14,20])
        self.assertEqual([r['full_name'] for r in subs[3]['rows'] if r['position_id']==6],['Андреев','Яковлев'])
        self.assertEqual(result['total_cents'],700)
        self.assertEqual((matrix,positions,categories),before)
