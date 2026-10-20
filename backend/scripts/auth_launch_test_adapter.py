"""Only for restricted own-cluster launch tests. Never accepts source DB credentials."""
import os

def build_isolated():
    if os.getenv('AUTH_ISOLATED_WORKER')!='1':raise RuntimeError('Worker required')
    db=os.environ['DB_NAME'];role=os.environ['DB_USER'];schema=os.environ['DB_SCHEMA']
    if not db.startswith('auth_stage3_') or not role.startswith('iso_test_') or schema!='test_construction_identity_stage46' or os.environ['DB_HOST']!='127.0.0.1':raise RuntimeError('Unsafe test configuration')
    import psycopg,dotenv
    dotenv.load_dotenv=lambda *a,**k:False
    from app.access_context import read_only_request
    def connection():
        from app.database.db import MatrixConnection
        c=MatrixConnection.connect(host='127.0.0.1',port=os.environ['DB_PORT'],dbname=db,user=role,password=os.environ['DB_PASSWORD'],options='-c search_path='+schema)
        if read_only_request.get():c.read_only=True
        return c
    with connection() as c:
        c.execute('SET TRANSACTION READ ONLY')
        if tuple(c.execute('SELECT current_database(),current_schema()').fetchone())!=(db,schema):raise RuntimeError('Wrong isolated target')
        if any(c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()):raise RuntimeError('Privileged test role refused')
    from app.database import db as database
    database.get_connection=connection
    from app.main import app
    from app.services.user_auth import AuthService
    class IsolatedService(AuthService):
        def connect(self):return connection()
    service=IsolatedService(connection)
    from app.api import user_auth
    user_auth.service=lambda:service
    from app.auth_ui import create_auth_ui
    return create_auth_ui(app,service),(db,schema)
