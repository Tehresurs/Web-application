import os
if os.environ.get('AUTH_ISOLATED_WORKER') != '1':
    raise RuntimeError('Use backend/scripts/run_auth_isolated.py; legacy DB fixtures are disabled')
"""Integration checks ONLY in restored auth_stage1_restore_<uuid> databases."""
import os
import unittest
from pathlib import Path
import psycopg
from psycopg import sql

SCHEMA='test_construction_identity_stage46'
MIGRATION=Path(__file__).resolve().parents[1]/'app/database/migrations/032_auth_structure.sql'
TABLES=['auth_users','auth_roles','auth_permissions','auth_user_roles','auth_role_permissions','auth_sessions','auth_security_events']

def connect():
    raise RuntimeError("Worker must supply restricted connection factory")
    name=os.environ['AUTH_TEST_DATABASE']
    if not name.startswith('auth_stage1_restore_') or not name[20:].isalnum():
        raise RuntimeError('Only isolated restore database allowed')
    return psycopg.connect(host=os.getenv('DB_HOST'),port=os.getenv('DB_PORT'),user=os.getenv('DB_USER'),password=os.getenv('DB_PASSWORD'),dbname=name,options='-c search_path='+SCHEMA)

class AuthStructureTests(unittest.TestCase):
    def setUp(self):
        self.c=connect()
        self.c.execute(MIGRATION.read_text(encoding='utf-8').replace("current_database() <> 'ai_excel_agent_test'", "current_database() <> '"+os.environ['AUTH_TEST_DATABASE']+"'"))
    def tearDown(self):
        self.c.rollback();self.c.close()
    def bad(self,statement,params=()):
        with self.assertRaises(psycopg.IntegrityError):
            with self.c.transaction():self.c.execute(statement,params)
    def user(self,login='test.user'):
        return self.c.execute('INSERT INTO auth_users(login) VALUES (%s) RETURNING id',(login,)).fetchone()[0]
    def test_empty_accounts_sessions_events_and_tables(self):
        for name in TABLES:
            self.assertIsNotNone(self.c.execute('SELECT to_regclass(%s)',(name,)).fetchone()[0])
        for name in ['auth_users','auth_user_roles','auth_sessions','auth_security_events']:
            self.assertEqual(self.c.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(name))).fetchone()[0],0)
    def test_exact_role_permissions(self):
        rows=self.c.execute('SELECT r.code,p.code FROM auth_roles r JOIN auth_role_permissions rp ON rp.role_id=r.id JOIN auth_permissions p ON p.id=rp.permission_id').fetchall()
        self.assertEqual(set(rows),{('SYSTEM_TECHNICIAN',p) for p in ['data.read','data.create','data.update','excel.export']}|{('OFFICE_MANAGER',p) for p in ['data.read','excel.export']})
        self.assertEqual(self.c.execute('SELECT count(*) FROM auth_permissions').fetchone()[0],4)
    def test_login_unique_and_normalized_and_blocked_default(self):
        uid=self.user();self.bad("INSERT INTO auth_users(login) VALUES ('test.user')")
        self.bad("INSERT INTO auth_users(login) VALUES (' Mixed ')")
        self.assertEqual(self.c.execute('SELECT is_blocked,password_hash FROM auth_users WHERE id=%s',(uid,)).fetchone(),(True,None))
        self.bad('UPDATE auth_users SET is_blocked=false WHERE id=%s',(uid,))
    def test_employee_fk_unique_restrict(self):
        emp=self.c.execute('SELECT id FROM employees ORDER BY id LIMIT 1').fetchone()[0]
        self.c.execute("INSERT INTO auth_users(login,employee_id) VALUES ('linked.user',%s)",(emp,))
        self.bad("INSERT INTO auth_users(login,employee_id) VALUES ('other.user',%s)",(emp,))
        self.bad("INSERT INTO auth_users(login,employee_id) VALUES ('missing.user',-999999)")
        self.bad('DELETE FROM employees WHERE id=%s',(emp,))
    def test_role_links_fk_and_unique(self):
        uid=self.user();rid=self.c.execute("SELECT id FROM auth_roles WHERE code='OFFICE_MANAGER'").fetchone()[0]
        self.c.execute('INSERT INTO auth_user_roles VALUES (%s,%s)',(uid,rid))
        self.bad('INSERT INTO auth_user_roles VALUES (%s,%s)',(uid,rid))
        self.bad('INSERT INTO auth_user_roles VALUES (%s,-1)',(uid,))
        self.bad('INSERT INTO auth_role_permissions VALUES (%s,-1)',(rid,))
        self.bad('INSERT INTO auth_role_permissions SELECT role_id,permission_id FROM auth_role_permissions LIMIT 1')
    def test_session_hash_dates_fk_and_revocation(self):
        uid=self.user();token='a'*64
        sid=self.c.execute("INSERT INTO auth_sessions(user_id,token_hash,credential_version,expires_at) VALUES (%s,%s,1,now()+interval '1 hour') RETURNING id",(uid,token)).fetchone()[0]
        self.bad("INSERT INTO auth_sessions(user_id,token_hash,credential_version,expires_at) VALUES (%s,%s,1,now()+interval '1 hour')",(uid,token))
        self.bad("INSERT INTO auth_sessions(user_id,token_hash,credential_version,expires_at) VALUES (%s,'raw-token',1,now()+interval '1 hour')",(uid,))
        self.bad("INSERT INTO auth_sessions(user_id,token_hash,credential_version,expires_at) VALUES (-1,%s,1,now()+interval '1 hour')",('b'*64,))
        self.bad("INSERT INTO auth_sessions(user_id,token_hash,credential_version,expires_at) VALUES (%s,%s,1,now()-interval '1 hour')",(uid,'c'*64))
        self.c.execute("UPDATE auth_sessions SET revoked_at=now(),revoked_reason='TEST' WHERE id=%s",(sid,))
        self.assertEqual(self.c.execute('SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL').fetchone()[0],0)
    def test_security_events_fk_and_shape(self):
        uid=self.user()
        self.c.execute("INSERT INTO auth_security_events(actor_user_id,subject_user_id,event_type,outcome) VALUES (%s,%s,'TEST','SUCCESS')",(uid,uid))
        self.bad("INSERT INTO auth_security_events(event_type,outcome) VALUES ('TEST','INVALID')")
        self.bad("INSERT INTO auth_security_events(event_type,outcome,details) VALUES ('TEST','SUCCESS','[]')")
        self.bad("INSERT INTO auth_security_events(actor_user_id,event_type,outcome) VALUES (-1,'TEST','SUCCESS')")
        self.bad('DELETE FROM auth_users WHERE id=%s',(uid,))
    def test_original_migration_rejects_wrong_database(self):
        with self.assertRaises(psycopg.errors.RaiseException):
            with self.c.transaction():self.c.execute(MIGRATION.read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
