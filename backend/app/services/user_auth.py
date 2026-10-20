"""Stage 2 session service. No implicit LEADER and no production writes."""
import hashlib
import hmac
import secrets
from psycopg.rows import dict_row
from app.database.db import get_connection

class AuthDenied(Exception): pass
class RateLimited(Exception): pass

class AuthService:
    def __init__(self, connection_factory=get_connection):
        from argon2 import PasswordHasher
        self.hasher=PasswordHasher(time_cost=3,memory_cost=65536,parallelism=1)
        self.dummy=self.hasher.hash(secrets.token_urlsafe(32))
        self.connection_factory=connection_factory
    def connect(self):
        c=self.connection_factory()
        try:
            if tuple(c.execute('SELECT current_database(),current_schema()').fetchone()) != ('ai_excel_agent_test','test_construction_identity_stage46'):
                raise RuntimeError('Wrong auth database/schema')
            return c
        except BaseException:c.close();raise
    @staticmethod
    def digest(value):return hashlib.sha256(value.encode()).hexdigest()
    def hash_password(self,password):
        if not 16<=len(password)<=1024:raise ValueError('Password length must be 16..1024')
        return self.hasher.hash(password)
    def event(self,c,kind,outcome,user=None,key=None):
        from psycopg.types.json import Jsonb
        c.execute('INSERT INTO auth_security_events(subject_user_id,event_type,outcome,details) VALUES (%s,%s,%s,%s)',(user,kind,outcome,Jsonb({'attempt_key':key} if key else {})))
    def login(self,login,password,peer):
        from argon2.exceptions import VerificationError,InvalidHashError
        login=login.strip().lower()
        # Stable account AND peer keys; never store raw credentials or login names.
        keys=[self.digest('account:'+login),self.digest('peer:'+peer)]
        denied=False;limited=False;result=None
        with self.connect() as c:
            # Serialize attempts across workers. Fixed order avoids advisory-lock deadlocks.
            for k in sorted(keys):c.execute('SELECT pg_advisory_xact_lock(%s)',(int(k[:15],16),))
            for key in keys:
                count=c.execute("SELECT count(*) FROM auth_security_events WHERE event_type='LOGIN_FAILURE' AND occurred_at>now()-interval '15 minutes' AND details->>'attempt_key'=%s",(key,)).fetchone()[0]
                if count>=10:limited=True
            if not limited:
                with c.cursor(row_factory=dict_row) as cur:
                    cur.execute('SELECT u.*,e.is_archived AS employee_archived FROM auth_users u LEFT JOIN employees e ON e.id=u.employee_id WHERE login=%s FOR UPDATE OF u',(login,));u=cur.fetchone()
                encoded=u['password_hash'] if u and u['password_hash'] else self.dummy
                valid=False
                try:valid=self.hasher.verify(encoded,password)
                except (VerificationError,InvalidHashError):pass
                if not u or not valid or u['is_blocked'] or u['employee_archived']:
                    for key in keys:self.event(c,'LOGIN_FAILURE','DENIED',key=key)
                    denied=True
                else:
                    token=secrets.token_urlsafe(32)
                    c.execute("INSERT INTO auth_sessions(user_id,token_hash,credential_version,expires_at) VALUES (%s,%s,%s,now()+interval '8 hours') RETURNING id",(u['id'],self.digest(token),u['credential_version'])).fetchone()[0]
                    self.event(c,'LOGIN_SUCCESS','SUCCESS',u['id']);result=token
        if limited:raise RateLimited()
        if denied:raise AuthDenied()
        return result
    def current(self,token):
        if not token or len(token)>128:raise AuthDenied()
        with self.connect() as c:
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT u.id,u.login,u.employee_id,s.id AS session_id FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id LEFT JOIN employees e ON e.id=u.employee_id WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>now() AND s.credential_version=u.credential_version AND NOT u.is_blocked AND (e.id IS NULL OR NOT e.is_archived)",(self.digest(token),));u=cur.fetchone()
            if not u:raise AuthDenied()
            roles=c.execute('SELECT r.code FROM auth_roles r JOIN auth_user_roles ur ON ur.role_id=r.id WHERE ur.user_id=%s ORDER BY r.code',(u['id'],)).fetchall()
            perms=c.execute('SELECT DISTINCT p.code FROM auth_permissions p JOIN auth_role_permissions rp ON rp.permission_id=p.id JOIN auth_user_roles ur ON ur.role_id=rp.role_id WHERE ur.user_id=%s ORDER BY p.code',(u['id'],)).fetchall()
            return {**u,'roles':[r[0] for r in roles],'permissions':[r[0] for r in perms]}
    def csrf(self,token):
        # Session token is never exposed to JavaScript; derived value is not a session credential.
        return hmac.new(token.encode(),b'tehresurs-csrf-v1',hashlib.sha256).hexdigest()
    def verify_csrf(self,token,supplied):
        if not token or not supplied or not hmac.compare_digest(self.csrf(token),supplied):raise AuthDenied()
    def logout(self,token):
        user=self.current(token)
        with self.connect() as c:
            c.execute("UPDATE auth_sessions SET revoked_at=now(),revoked_reason='LOGOUT' WHERE id=%s AND revoked_at IS NULL",(user['session_id'],))
            self.event(c,'LOGOUT','SUCCESS',user['id'])
    def revoke_all(self,user_id):
        # Internal service only: no public administrative route at stage 2.
        with self.connect() as c:
            c.execute("UPDATE auth_sessions SET revoked_at=now(),revoked_reason='REVOKED' WHERE user_id=%s AND revoked_at IS NULL",(user_id,))
            self.event(c,'SESSIONS_REVOKED','SUCCESS',user_id)
