import asyncio
import json
import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import psycopg
import test_luvr_history
from rail_fixture import coupon_pdf,combine_pdfs
from test_daily_control import http_request
from app.database.migrate_rail_tickets import apply_migration
from app.database.migrate_rail_ticket_pages import apply_migration as page_migration
from app.repositories import rail_tickets


def upload_request(files):
    from app.main import app
    boundary='test-rail-boundary';chunks=[]
    for filename,data in files:
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n'.encode()+data+b'\r\n')
    body=b''.join(chunks)+f'--{boundary}--\r\n'.encode()
    async def run():
        messages=[]
        async def receive():return {'type':'http.request','body':body,'more_body':False}
        async def send(message):messages.append(message)
        await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http','path':'/api/rail-tickets/upload','raw_path':b'/api/rail-tickets/upload','query_string':b'','root_path':'','headers':[(b'content-type',f'multipart/form-data; boundary={boundary}'.encode())],'server':('test',80),'client':('test',1)},receive,send)
        return messages[0]['status'],json.loads(b''.join(m.get('body',b'') for m in messages[1:]))
    return asyncio.run(run())


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class RailTicketTests(unittest.TestCase):
    def setUp(self):
        test_luvr_history.LuvrHistoryTests.setUp(self)
        apply_migration(self.conn)
        page_migration(self.conn)
        self.conn.execute("UPDATE employees SET full_name='Иванов Иван Иванович' WHERE id=2")
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        mock=patch('app.repositories.rail_tickets.get_connection',connection);mock.start();self.addCleanup(mock.stop)

    def upload(self,data=None,filename='ticket.pdf'):
        status,body=upload_request([(filename,data if data is not None else coupon_pdf())])
        self.assertEqual(status,200,body);return body['items'][0]

    def action(self,item,op,payload=None):
        return http_request('PATCH' if op=='direction' else 'POST',f'/api/rail-tickets/{item["id"]}/{op}',payload or {})

    def count_movements(self):return self.conn.execute('SELECT count(*) FROM employee_movements').fetchone()[0]

    def test_real_round_trip_two_records_two_confirmations_and_duplicate_upload(self):
        data=(Path(__file__).parent/'fixtures/rail/round_trip.pdf').read_bytes()
        self.conn.execute("UPDATE employees SET full_name='Каньшин Егор Викторович' WHERE id=2")
        status,body=upload_request([('round.pdf',data)])
        self.assertEqual(status,200);first,second=body['items']
        self.assertNotEqual(first['file_hash'],second['file_hash']);self.assertEqual(first['source_sha256'],second['source_sha256'])
        self.assertEqual([first['source_page'],second['source_page']],[1,2]);self.assertEqual(self.count_movements(),0)
        a=self.action(first,'confirm')[1]['item'];self.assertEqual(self.count_movements(),1)
        self.assertEqual(http_request('GET',f'/api/rail-tickets/{second["id"]}')[1]['item']['processing_status'],'READY')
        b=self.action(second,'confirm')[1]['item'];self.assertEqual(self.count_movements(),2)
        self.assertEqual(a['movement']['event_datetime'],'2026-10-09T06:54:00');self.assertEqual(b['movement']['event_datetime'],'2026-10-12T07:29:00')
        repeated=upload_request([('renamed.pdf',data)])[1]['items']
        self.assertEqual([x['id'] for x in repeated],[first['id'],second['id']]);self.assertTrue(all(x['processing_status']=='DUPLICATE' for x in repeated))
        self.assertEqual(self.count_movements(),2)

    def test_each_page_filters_matches_and_fails_independently(self):
        data=combine_pdfs(coupon_pdf(),coupon_pdf(full_name='ДРУГОЙ ИВАН ИВАНОВИЧ'),coupon_pdf(departure_station='Сургут',arrival_station='Тюмень'),coupon_pdf(arrival_datetime=None),coupon_pdf(header=False))
        items=upload_request([('five.pdf',data)])[1]['items']
        self.assertEqual([x['processing_status'] for x in items],['READY','EMPLOYEE_NOT_FOUND','NOT_LUVR_ROUTE','PARSE_ERROR','UNSUPPORTED'])
        self.assertEqual(items[0]['employee_id'],2);self.assertIsNone(items[1]['employee_id'])
        self.assertEqual(self.action(items[0],'confirm')[0],200)
        for item in items[1:4]:self.assertEqual(self.action(item,'confirm')[0],409)
        self.assertEqual(self.count_movements(),1)

    def test_page_migration_idempotent_preserves_confirmed_rows(self):
        ticket=self.upload();self.action(ticket,'confirm')
        before=self.conn.execute('SELECT to_jsonb(t) FROM rail_tickets t ORDER BY id').fetchall()
        page_migration(self.conn)
        self.assertEqual(before,self.conn.execute('SELECT to_jsonb(t) FROM rail_tickets t ORDER BY id').fetchall())

    def test_upload_auto_direction_never_creates_movement_without_confirmation(self):
        item=self.upload();self.assertEqual(item['processing_status'],'READY');self.assertEqual(item['match_status'],'FOUND')
        self.assertEqual(item['movement_type'],'ARRIVAL');self.assertEqual(self.count_movements(),0)
        self.assertEqual(self.action(item,'confirm')[0],200)

    def test_exact_case_spaces_only(self):
        for name in ('Иванов Иван Иванович','иванов иван иванович','  ИВАНОВ   ИВАН ИВАНОВИЧ  '):
            self.conn.execute('UPDATE employees SET full_name=%s WHERE id=2',(name,))
            self.assertEqual(self.upload()['match_status'],'FOUND')
        for name in ('Иванов Иван Петрович','Иванов И.И.','Иваноф Иван Иванович'):
            self.conn.execute('UPDATE employees SET full_name=%s WHERE id=2',(name,))
            self.assertEqual(self.upload()['match_status'],'NOT_FOUND')

    def test_aliases_and_daily_fuzzy_never_used(self):
        self.conn.execute("UPDATE employees SET full_name='Иванов Иван Петрович' WHERE id=2")
        self.conn.execute("INSERT INTO value_aliases(entity_type,source_value,target_id) VALUES('employee','ИВАНОВ ИВАН ИВАНОВИЧ',2)")
        with patch('app.repositories.value_aliases.resolve_value_alias',side_effect=AssertionError('aliases forbidden')),patch('app.services.employee_matcher.match_employee',side_effect=AssertionError('fuzzy forbidden')):
            self.assertEqual(self.upload()['match_status'],'NOT_FOUND')

    def test_not_found_create_employee_then_reuse_parsed_ticket(self):
        item=self.upload(coupon_pdf(full_name='НОВЫЙ ИВАН ИВАНОВИЧ'))
        self.assertEqual(item['processing_status'],'EMPLOYEE_NOT_FOUND')
        self.action(item,'direction',{'movement_type':'ARRIVAL'})
        self.assertEqual(self.action(item,'confirm')[0],409)
        status,employee=http_request('POST','/api/employees',{'full_name':'Новый Иван Иванович','nrs_number':'НРС'})
        self.assertEqual(status,200)
        view=http_request('GET',f'/api/rail-tickets/{item["id"]}')[1]['item']
        self.assertEqual(view['employee_id'],employee['id']);self.assertEqual(view['processing_status'],'READY')
        self.assertEqual(self.action(item,'confirm')[0],200);self.assertEqual(self.count_movements(),1)

    def test_archived_employee_never_auto_restored(self):
        http_request('POST','/api/employees/2/archive')
        item=self.upload();self.assertEqual(item['processing_status'],'ARCHIVED_EMPLOYEE')
        self.action(item,'direction',{'movement_type':'ARRIVAL'})
        before=self.conn.execute('SELECT to_jsonb(e) FROM employees e WHERE id=2').fetchone()
        self.assertEqual(self.action(item,'confirm')[0],409);self.assertEqual(self.count_movements(),0)
        self.assertEqual(before,self.conn.execute('SELECT to_jsonb(e) FROM employees e WHERE id=2').fetchone())
        http_request('POST','/api/employees/2/restore');self.assertEqual(self.action(item,'confirm')[0],200)

    def test_new_employee_title_case_preserves_raw_ticket_and_existing_employees(self):
        before=self.conn.execute('SELECT id,full_name FROM employees ORDER BY id').fetchall()
        raw='ТРОФИМОВ СЕРГЕЙ НИКОЛАЕВИЧ'
        item=self.upload(coupon_pdf(full_name=raw))
        self.assertEqual(item['match_status'],'NOT_FOUND')
        status,created=http_request('POST','/api/employees',{'full_name':'Трофимов Сергей Николаевич'})
        self.assertEqual(status,200)
        self.assertEqual(self.conn.execute('SELECT full_name FROM employees WHERE id=%s',(created['id'],)).fetchone()[0],'Трофимов Сергей Николаевич')
        view=http_request('GET',f'/api/rail-tickets/{item["id"]}')[1]['item']
        self.assertEqual(view['match_status'],'FOUND');self.assertEqual(view['employee_id'],created['id']);self.assertEqual(view['full_name'],raw)
        self.assertEqual(self.conn.execute('SELECT id,full_name FROM employees WHERE id<>%s ORDER BY id',(created['id'],)).fetchall(),before)
        typo=self.upload(coupon_pdf(full_name='ТРОФИМАВ СЕРГЕЙ НИКОЛАЕВИЧ'))
        self.assertEqual(typo['match_status'],'NOT_FOUND')

    def test_archive_after_preview_rechecked_at_confirmation(self):
        item=self.upload();self.action(item,'direction',{'movement_type':'ARRIVAL'});http_request('POST','/api/employees/2/archive')
        self.assertEqual(self.action(item,'confirm')[0],409);self.assertEqual(self.count_movements(),0)

    def test_arrival_uses_arrival_datetime_and_preserves_route(self):
        item=self.upload();self.action(item,'direction',{'movement_type':'ARRIVAL'})
        status,body=self.action(item,'confirm');self.assertEqual(status,200)
        movement=body['item']['movement'];self.assertEqual(movement['transport_type'],'RAIL')
        self.assertEqual(movement['event_datetime'],'2026-09-11T07:29:00')
        self.assertEqual((movement['departure_station'],movement['arrival_station']),('Тюмень','Салым'))

    def test_departure_uses_departure_datetime(self):
        item=self.upload(coupon_pdf(departure_station='Салым',arrival_station='Сургут'))
        self.assertEqual(self.action(item,'confirm')[1]['item']['movement']['event_datetime'],'2026-09-10T23:04:00')

    def test_confirm_repeat_upload_and_rename_deduplicated(self):
        item=self.upload();self.action(item,'direction',{'movement_type':'ARRIVAL'})
        movement=self.action(item,'confirm')[1]['item']['movement_id']
        repeated=self.upload(filename='renamed.pdf')
        self.assertEqual(repeated['processing_status'],'DUPLICATE');self.assertEqual(repeated['id'],item['id'])
        self.assertEqual(repeated['movement_id'],movement)
        self.assertEqual(self.action(item,'confirm')[1]['item']['movement_id'],movement)
        self.assertEqual(self.count_movements(),1)

    def test_unfinished_duplicate_keeps_direction(self):
        item=self.upload()
        duplicate=self.upload(filename='folder/renamed.pdf')
        self.assertEqual(item['id'],duplicate['id']);self.assertEqual(duplicate['movement_type'],'ARRIVAL')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM rail_tickets').fetchone()[0],1)

    def test_same_filename_different_content_and_same_time_not_heuristic_duplicate(self):
        first=self.upload();second=self.upload(coupon_pdf(departure_station='Другая станция'))
        self.assertNotEqual(first['id'],second['id'])
        for item in (first,second):self.action(item,'direction',{'movement_type':'ARRIVAL'});self.assertEqual(self.action(item,'confirm')[0],200)
        self.assertEqual(self.count_movements(),2)

    def test_rejection_persisted_no_movement(self):
        item=self.upload();self.assertEqual(self.action(item,'reject')[1]['item']['processing_status'],'REJECTED')
        self.assertEqual(self.upload()['processing_status'],'REJECTED');self.assertEqual(self.action(item,'confirm')[0],409)
        self.assertEqual(self.count_movements(),0)

    def test_batch_success_notfound_error_duplicate_independent(self):
        known=self.upload();self.action(known,'direction',{'movement_type':'ARRIVAL'});self.action(known,'confirm')
        status,body=upload_request([('ok.pdf',coupon_pdf(departure_station='Новая')),('unknown.pdf',coupon_pdf(full_name='НЕИЗВЕСТНЫЙ ИВАН ИВАНОВИЧ')),('broken.pdf',b'%PDF-broken'),('duplicate.pdf',coupon_pdf())])
        self.assertEqual(status,200)
        self.assertEqual([i['processing_status'] for i in body['items']],['READY','EMPLOYEE_NOT_FOUND','PARSE_ERROR','DUPLICATE'])
        self.assertEqual(self.count_movements(),1)

    def test_file_validation_empty_oversize_content_filename(self):
        from app.services.rail_ticket_parser import MAX_TICKET_BYTES
        for data,name in ((b'','empty.pdf'),(b'%PDF-'+b'x'*MAX_TICKET_BYTES,'big.pdf')):
            self.assertEqual(self.upload(data,name)['processing_status'],'PARSE_ERROR')
        for data,name in ((b'not a pdf','fake.pdf'),(coupon_pdf(),'fake.txt')):
            self.assertEqual(self.upload(data,name)['processing_status'],'UNSUPPORTED')
        item=self.upload(coupon_pdf(departure_station='Безопасное имя'),filename='../../ticket.pdf')
        self.assertEqual(item['source_filename'],'ticket.pdf')

    def test_multiple_exact_names_require_review(self):
        self.conn.execute("INSERT INTO employees(id,full_name) VALUES(999,'ИВАНОВ ИВАН ИВАНОВИЧ')")
        item=self.upload();self.assertTrue(item['match_ambiguous']);self.assertEqual(item['match_status'],'NOT_FOUND')
        self.action(item,'direction',{'movement_type':'ARRIVAL'});self.assertEqual(self.action(item,'confirm')[0],409)

    def test_confirm_tampering_rejected(self):
        item=self.upload()
        self.assertEqual(self.action(item,'confirm',{'employee_id':1,'event_datetime':'2026-01-01T00:00'})[0],422)
        self.assertEqual(self.action(item,'direction',{'movement_type':'BAD'})[0],422)
        self.assertEqual(self.count_movements(),0)

    def test_self_unchanged_and_ticket_movement_protected(self):
        status,body=http_request('POST','/api/employees/2/luvr/movements',{'movement_type':'ARRIVAL','transport_type':'SELF','event_datetime':'2026-09-11T07:29:00'})
        self.assertEqual(status,200);self_id=body['item']['id']
        before=self.conn.execute('SELECT to_jsonb(m) FROM employee_movements m WHERE id=%s',(self_id,)).fetchone()
        item=self.upload();self.action(item,'direction',{'movement_type':'ARRIVAL'});movement=self.action(item,'confirm')[1]['item']['movement_id']
        self.assertEqual(before,self.conn.execute('SELECT to_jsonb(m) FROM employee_movements m WHERE id=%s',(self_id,)).fetchone())
        for method,data in [('DELETE',{}),('PATCH',{'movement_type':'DEPARTURE'})]:
            self.assertEqual(http_request(method,f'/api/employees/2/luvr/movements/{movement}',data)[0],409)
        self.assertEqual(http_request('PATCH',f'/api/employees/2/luvr/movements/{self_id}',{'movement_type':'DEPARTURE'})[0],200)
        self.assertEqual(http_request('DELETE',f'/api/employees/2/luvr/movements/{self_id}')[0],200)

    def test_database_hash_unique_movement_unique_and_fk_restrict(self):
        item=self.upload();self.action(item,'direction',{'movement_type':'ARRIVAL'});confirmed=self.action(item,'confirm')[1]['item']
        with self.assertRaises(psycopg.errors.UniqueViolation),self.conn.transaction():
            self.conn.execute("INSERT INTO rail_tickets(file_hash,source_filename,status) VALUES(%s,'x.pdf','PARSED')",(item['file_hash'],))
        with self.assertRaises((psycopg.errors.ForeignKeyViolation,psycopg.errors.RestrictViolation)),self.conn.transaction():
            self.conn.execute('DELETE FROM employee_movements WHERE id=%s',(confirmed['movement_id'],))
        with self.assertRaises(psycopg.errors.CheckViolation),self.conn.transaction():
            self.conn.execute("UPDATE rail_tickets SET movement_id=NULL WHERE id=%s",(item['id'],))

    def test_failed_confirmation_rolls_back_movement(self):
        item=self.upload();self.action(item,'direction',{'movement_type':'ARRIVAL'})
        # Force failure after movement INSERT, before ticket confirmation can finish.
        self.conn.execute("ALTER TABLE rail_tickets ADD CONSTRAINT test_no_confirmation CHECK(status<>'CONFIRMED')")
        with self.assertRaises(psycopg.errors.CheckViolation):rail_tickets.confirm_ticket(item['id'])
        self.assertEqual(self.count_movements(),0);self.assertEqual(self.conn.execute('SELECT status FROM rail_tickets WHERE id=%s',(item['id'],)).fetchone()[0],'PARSED')
        self.assertEqual(self.conn.execute('SELECT 1').fetchone()[0],1)

    def test_migration_repeat_preserves_existing_rows(self):
        self.upload()
        names=['employees','positions','employee_assignments','daily_control_results','value_aliases','employee_movements','employee_sick_periods','employee_duration_exceptions','employee_luvr_day_overrides','rail_tickets']
        before={t:self.conn.execute(f'SELECT to_jsonb(r) FROM {t} r ORDER BY id').fetchall() for t in names}
        apply_migration(self.conn)
        self.assertEqual(before,{t:self.conn.execute(f'SELECT to_jsonb(r) FROM {t} r ORDER BY id').fetchall() for t in names})

    def test_openapi_routes(self):
        schema=http_request('GET','/openapi.json')[1]
        for route,method in [('/upload','post'),('/{ticket_id}','get'),('/{ticket_id}/direction','patch'),('/{ticket_id}/confirm','post'),('/{ticket_id}/reject','post')]:
            self.assertIn(method,schema['paths']['/api/rail-tickets'+route])

    def test_salym_exact_route_filter_and_candidates(self):
        for departure,arrival,candidate in [('Салым','Сургут','DEPARTURE'),('Салым','Тюмень','DEPARTURE'),('Сургут','Салым','ARRIVAL'),('Тюмень','Салым','ARRIVAL'),('  САЛЫМ  ','Тюмень','DEPARTURE')]:
            with self.subTest(departure=departure,arrival=arrival):
                item=self.upload(coupon_pdf(departure_station=departure,arrival_station=arrival))
                self.assertTrue(item['is_luvr_route']);self.assertEqual(item['direction_candidate'],candidate)
                self.assertEqual(item['processing_status'],'READY');self.assertEqual(item['movement_type'],candidate)
                result=self.action(item,'confirm')[1]['item']['movement']
                self.assertEqual(result['movement_type'],candidate)
                self.assertEqual(result['event_datetime'],item['arrival_datetime'] if candidate=='ARRIVAL' else item['departure_datetime'])

    def test_ambiguous_or_incomplete_route_never_matches_or_creates_movement(self):
        for fields in ({'departure_station':'Салым','arrival_station':'Салым'},{'departure_station':None},{'arrival_station':None}):
            with patch('app.repositories.rail_tickets._employee',side_effect=AssertionError('Must not match invalid route')):
                item=self.upload(coupon_pdf(**fields))
                self.assertEqual(item['processing_status'],'PARSE_ERROR');self.assertIsNone(item['movement_type'])
                self.assertEqual(self.action(item,'confirm')[0],409)
        self.assertEqual(self.count_movements(),0)

    def test_manual_or_stale_direction_cannot_override_route(self):
        item=self.upload()
        self.assertEqual(self.action(item,'direction',{'movement_type':'DEPARTURE'})[0],409)
        self.conn.execute("UPDATE rail_tickets SET movement_type='DEPARTURE' WHERE id=%s",(item['id'],))
        self.assertEqual(http_request('GET',f'/api/rail-tickets/{item["id"]}')[1]['item']['movement_type'],'ARRIVAL')
        confirmed=self.action(item,'confirm')[1]['item']
        self.assertEqual(confirmed['movement_type'],'ARRIVAL');self.assertEqual(confirmed['movement']['event_datetime'],item['arrival_datetime'])

    def test_no_salym_stops_before_matching_and_blocks_all_confirmation(self):
        for departure,arrival in [('Сургут','Тюмень'),('Салымский','Тюмень'),('Салым 2','Тюмень')]:
            with patch('app.repositories.rail_tickets._employee',side_effect=AssertionError('Matching must not run')):
                item=self.upload(coupon_pdf(departure_station=departure,arrival_station=arrival))
                self.assertEqual(item['processing_status'],'NOT_LUVR_ROUTE');self.assertEqual(item['parse_errors'],[])
                self.assertIsNone(item['employee_id']);self.assertFalse(item['is_luvr_route'])
                self.assertEqual(http_request('GET',f'/api/rail-tickets/{item["id"]}')[1]['item']['processing_status'],'NOT_LUVR_ROUTE')
                self.assertEqual(self.action(item,'direction',{'movement_type':'ARRIVAL'})[0],409)
                self.conn.execute("UPDATE rail_tickets SET movement_type='ARRIVAL' WHERE id=%s",(item['id'],))
                self.assertEqual(self.action(item,'confirm')[0],409)
        self.assertEqual(self.count_movements(),0)

    def test_nested_folder_same_bytes_and_mixed_files(self):
        data=coupon_pdf()
        status,body=upload_request([('root.pdf',data),('first.pdf',data),('deep.pdf',data),('other.txt',b'hello'),('broken.pdf',b'%PDF-broken'),('outside.pdf',coupon_pdf(departure_station='Сургут',arrival_station='Тюмень'))])
        self.assertEqual(status,200)
        items=body['items'];self.assertEqual(len({x['id'] for x in items[:3]}),1)
        self.assertTrue(items[1]['duplicate']);self.assertTrue(items[2]['duplicate'])
        self.assertEqual([x['processing_status'] for x in items[3:]],['UNSUPPORTED','PARSE_ERROR','NOT_LUVR_ROUTE'])
        self.assertEqual(self.count_movements(),0)
