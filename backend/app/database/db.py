import os
from pathlib import Path
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv

_backend_dir = Path(__file__).resolve().parents[2]
load_dotenv(_backend_dir / ".env")

if os.getenv("APP_DB_PROFILE") == "test":
    test_env = _backend_dir / ".env.test"
    if not test_env.is_file():
        raise RuntimeError(f"Test database configuration not found: {test_env}")
    load_dotenv(test_env, override=True)



class MatrixConnection(psycopg.Connection):
    """Reconcile DK in the same transaction as calendar source changes."""
    def _reconcile_dk(self):
        from psycopg.pq import TransactionStatus
        from psycopg.rows import tuple_row
        if self.info.transaction_status != TransactionStatus.INTRANS:return
        with self.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT current_setting('tehresurs.dk_calendar_dirty',true)")
            dirty=cur.fetchone()[0]
        if dirty=='1':
            from app.services.matrix_dk import reconcile
            reconcile(self)
            self.execute("SELECT set_config('tehresurs.dk_calendar_dirty','0',true)")

    def commit(self):
        try:
            self._reconcile_dk()
            return super().commit()
        except Exception:
            self.rollback()
            raise

    @contextmanager
    def transaction(self,*args,**kwargs):
        # psycopg transaction contexts issue COMMIT without calling commit().
        with super().transaction(*args,**kwargs) as tx:
            yield tx
            self._reconcile_dk()


def get_connection():
    connection_options = {}
    if os.getenv("APP_DB_PROFILE") == "test":
        database = os.getenv("DB_NAME")
        schema = os.getenv("DB_SCHEMA")
        if database != "ai_excel_agent_test":
            raise RuntimeError(f"Refusing test profile database: {database!r}")
        if not schema or not schema.replace("_", "").isalnum() or not schema.startswith("test_"):
            raise RuntimeError(f"Refusing invalid test profile schema: {schema!r}")
        connection_options["options"] = f"-c search_path={schema}"
    from app.access_context import read_only_request
    viewer=read_only_request.get()
    if viewer:
        connection_options['options']=connection_options.get('options','')+' -c default_transaction_read_only=on'
    conn=MatrixConnection.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        **connection_options,
    )
    if viewer:
        try:
            conn.read_only=True
            actual=conn.execute('SELECT current_database(),current_schema()').fetchone()
            if actual!=('ai_excel_agent_test','test_construction_identity_stage46'):
                raise RuntimeError('Demo reads are restricted to the 8001 database/schema')
            conn.rollback()
        except BaseException:
            conn.close()
            raise
    return conn



def test_connection():
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_database();")
                database_name = cursor.fetchone()[0]

                print("Подключение к PostgreSQL успешно")
                print(f"База данных: {database_name}")

    except Exception as error:
        print("Ошибка подключения к PostgreSQL:")
        print(error)


if __name__ == "__main__":
    test_connection()
