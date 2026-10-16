import os
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest.mock import patch

from psycopg import sql
from app.database.db import get_connection
from app.database.migrate_luvr_history import apply_migration as history_migration
from app.database.migrate_rail_tickets import apply_migration
from app.repositories.rail_tickets import choose_direction,confirm_ticket,annul_ticket,restore_ticket
from app.services.rail_ticket_service import process_ticket
from rail_fixture import coupon_pdf


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class RailConcurrencyTests(unittest.TestCase):
    def test_parallel_upload_and_confirmation_create_one_ticket_and_movement(self):
        schema='test_rail_concurrency_'+uuid4().hex
        with get_connection() as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
            conn.execute("CREATE TABLE employees(id BIGSERIAL PRIMARY KEY,full_name TEXT,is_archived BOOLEAN NOT NULL DEFAULT FALSE)")
            history_migration(conn);apply_migration(conn)
            conn.execute('CREATE TABLE positions(id BIGINT PRIMARY KEY,name TEXT)')
            conn.execute('CREATE TABLE construction_objects(id BIGINT PRIMARY KEY,name TEXT)')
            conn.execute('ALTER TABLE employees ADD COLUMN position_id BIGINT, ADD COLUMN max_shift_days INT, ADD COLUMN max_off_shift_days INT')
            for name in ('015_rail_ticket_management.sql','016_rail_ticket_restore.sql'):
                conn.execute((Path(__file__).resolve().parents[1]/'app/database/migrations'/name).read_text(encoding='utf-8'))
            conn.execute("INSERT INTO employees(full_name) VALUES('Иванов Иван Иванович')")
        def connect():
            conn=get_connection()
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            return conn
        try:
            with patch('app.repositories.rail_tickets.get_connection',connect),ThreadPoolExecutor(max_workers=3) as pool:
                data=coupon_pdf()
                tickets=list(pool.map(lambda n:process_ticket(data,f'copy{n}.pdf'),range(3)))
                self.assertEqual(len({t['id'] for t in tickets}),1)
                ticket_id=tickets[0]['id'];choose_direction(ticket_id,'ARRIVAL')
                confirmed=list(pool.map(lambda _:confirm_ticket(ticket_id),range(3)))
                self.assertEqual(len({t['movement_id'] for t in confirmed}),1)
                original_id=confirmed[0]['movement_id']
                list(pool.map(lambda _:annul_ticket(ticket_id),range(3)))
                restored=list(pool.map(lambda _:restore_ticket(ticket_id),range(3)))
                self.assertEqual({t['movement_id'] for t in restored},{original_id})
                with connect() as conn:
                    self.assertEqual(conn.execute('SELECT count(*) FROM rail_tickets').fetchone()[0],1)
                    self.assertEqual(conn.execute('SELECT count(*) FROM employee_movements').fetchone()[0],1)
        finally:
            with get_connection() as conn:conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
