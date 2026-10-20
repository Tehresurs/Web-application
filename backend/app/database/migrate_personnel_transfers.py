"""Explicit additive installer. Never executed on import or app startup."""
import hashlib,json
from pathlib import Path
from psycopg import sql
SCHEMA='test_construction_identity_stage46'
def apply_migration(connection,verified_backup,*,expected_database='ai_excel_agent_test'):
    manifest=json.loads(Path(verified_backup).read_text(encoding='utf-8'))
    backup=Path(manifest['backup_path'])
    if not manifest.get('restoration_verified') or manifest.get('source_database')!='ai_excel_agent_test' or (expected_database!='ai_excel_agent_test' and manifest.get('restored_database')!=expected_database):
        raise RuntimeError('A verified restore of this database is required before migration')
    if hashlib.sha256(backup.read_bytes()).hexdigest()!=manifest['backup_sha256']:
        raise RuntimeError('Backup checksum mismatch')
    with connection.transaction():
        if connection.execute('SELECT current_database(),current_schema()').fetchone()!=(expected_database,SCHEMA):
            raise RuntimeError('Wrong personnel migration target')
        connection.execute("SET LOCAL lock_timeout='3s'")
        connection.execute("SET LOCAL statement_timeout='30s'")
        connection.execute('SELECT pg_advisory_xact_lock(20261017,29)')
        if connection.execute("SELECT to_regclass('personnel_settings')").fetchone()[0]:
            raise RuntimeError('Personnel migration already installed; refusing to rewrite history')
        text=(Path(__file__).with_name('migrations')/'033_personnel_transfers.sql').read_text(encoding='utf-8')
        connection.execute(sql.SQL(text.replace('__SCHEMA__',sql.Identifier(SCHEMA).as_string(connection))))


def apply_movements_migration(connection,verified_backup,*,expected_database):
    """Explicit extension, protected by the same verified restore manifest."""
    manifest=json.loads(Path(verified_backup).read_text(encoding='utf-8'))
    backup=Path(manifest['backup_path'])
    if not manifest.get('restoration_verified') or manifest.get('source_database')!='ai_excel_agent_test' or (expected_database!='ai_excel_agent_test' and manifest.get('restored_database')!=expected_database):
        raise RuntimeError('Verified restore required')
    if hashlib.sha256(backup.read_bytes()).hexdigest()!=manifest['backup_sha256']:raise RuntimeError('Backup checksum mismatch')
    with connection.transaction():
        if connection.execute('SELECT current_database(),current_schema()').fetchone()!=(expected_database,SCHEMA):raise RuntimeError('Wrong migration target')
        connection.execute("SET LOCAL lock_timeout='3s'")
        connection.execute('SELECT pg_advisory_xact_lock(20261017,29)')
        if not connection.execute("SELECT to_regclass('personnel_settings')").fetchone()[0]:raise RuntimeError('Install 033 first')
        if connection.execute("SELECT to_regclass('personnel_acting_events')").fetchone()[0]:raise RuntimeError('Movements already installed')
        text=(Path(__file__).with_name('migrations')/'034_personnel_movements.sql').read_text(encoding='utf-8')
        connection.execute(sql.SQL(text.replace('__SCHEMA__',sql.Identifier(SCHEMA).as_string(connection))))
