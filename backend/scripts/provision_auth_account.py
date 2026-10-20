"""Inactive interactive bootstrap. No account creation without --apply and a TTY."""
import sys,re,getpass,hmac
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
TARGET=('ai_excel_agent_test','test_construction_identity_stage46')
ROLES={'SYSTEM_TECHNICIAN','OFFICE_MANAGER'}

def password_hash(password,confirmation):
    if not hmac.compare_digest(password.encode('utf-8'),confirmation.encode('utf-8')):raise ValueError('Passwords differ')
    if not 16<=len(password)<=1024:raise ValueError('Password length must be 16..1024')
    from argon2 import PasswordHasher
    return PasswordHasher(time_cost=3,memory_cost=65536,parallelism=1).hash(password)

def create_account(c,login,employee_id,role,encoded,expected=TARGET):
    if tuple(c.execute('SELECT current_database(),current_schema()').fetchone())!=expected:raise ValueError('Wrong database/schema')
    if role not in ROLES or not isinstance(employee_id,int) or employee_id<=0:raise ValueError('Invalid account binding')
    login=login.strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{2,63}',login):raise ValueError('Invalid login')
    if not encoded.startswith('$argon2id$'):raise ValueError('Argon2id required')
    if not c.execute('SELECT id FROM employees WHERE id=%s AND NOT is_archived',(employee_id,)).fetchone():raise ValueError('Active employee required')
    rid=c.execute('SELECT id FROM auth_roles WHERE code=%s',(role,)).fetchone()
    if not rid:raise ValueError('Role missing')
    # Caller owns one transaction. Uniqueness/FK violations roll back everything.
    uid=c.execute('INSERT INTO auth_users(login,employee_id,password_hash,is_blocked,password_changed_at) VALUES (%s,%s,%s,false,now()) RETURNING id',(login,employee_id,encoded)).fetchone()[0]
    c.execute('INSERT INTO auth_user_roles(user_id,role_id) VALUES (%s,%s)',(uid,rid[0]))
    for event in ('USER_CREATED','PASSWORD_INITIALIZED'):
        c.execute("INSERT INTO auth_security_events(subject_user_id,event_type,outcome,details) VALUES (%s,%s,'SUCCESS','{}'::jsonb)",(uid,event))
    return uid

def main():
    import argparse
    parser=argparse.ArgumentParser(description='Interactive local bootstrap; passwords are never command arguments.')
    parser.add_argument('--apply',action='store_true',help='Explicitly authorize one interactive account creation')
    args=parser.parse_args()
    if not args.apply:
        print('CHECK ONLY: no database connection and no accounts created. Use --apply only after separate approval.')
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('A private interactive console is required; redirected input/output is refused.');return 1
    try:
        login=input('Login (ASCII, 3..64): ')
        employee=int(input('Existing employee ID: '))
        role=input('Role (SYSTEM_TECHNICIAN / OFFICE_MANAGER): ').strip()
        if input('Type CREATE to confirm this single account: ')!='CREATE':return 1
        import warnings
        warnings.simplefilter('error',getpass.GetPassWarning)
        password=getpass.getpass('Initial password (16+ characters): ')
        confirmation=getpass.getpass('Repeat password: ')
        encoded=password_hash(password,confirmation)
        password=confirmation=None
        # Match the verified launcher: dotenv import first, then exact DB/schema.
        import os
        os.environ['APP_DB_PROFILE']='test'
        from app.database.db import get_connection
        os.environ.update(DB_NAME=TARGET[0],DB_SCHEMA=TARGET[1],APP_TEST_ALLOWED_DB_SCHEMAS=TARGET[1])
        with get_connection() as c:uid=create_account(c,login,employee,role,encoded)
        encoded=None
        print('Account created. User ID: '+str(uid));return 0
    except (Exception,KeyboardInterrupt):
        # Do not echo credentials, hashes, SQL parameters or driver error details.
        print('Account not created or result requires verification. No automatic retry; inspect account metadata safely.');return 1

if __name__=='__main__':raise SystemExit(main())
