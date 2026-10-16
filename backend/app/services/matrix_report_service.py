"""One-file entry into the existing parser/review/fact pipeline."""
from pathlib import Path
from hashlib import sha256
from io import BytesIO
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.database.db import get_connection
from app.parsers.word_parser import read_document
from app.services.processing_service import prepare_report
from app.repositories import report_review
from app.repositories.daily_control_identity import read
from app.repositories.directory_errors import DirectoryConflict


def has_archive(conn):
    return conn.execute("SELECT to_regclass('daily_control_fact_replacements')").fetchone()[0] is not None


def ensure_current_source(conn,digest):
    if has_archive(conn) and conn.execute('SELECT 1 FROM daily_control_fact_replacements WHERE old_source_sha256=%s LIMIT 1',(digest,)).fetchone():
        raise DirectoryConflict('Этот отчёт уже заменён исправленным. Повторное сохранение старой версии запрещено.')


def inspect_fact(fact_id):
    with get_connection() as conn:
        rows=read(conn,'r.id=%s',(fact_id,))
        if not rows:raise ValueError('Факт не найден. Обновите матрицу.')
        row=rows[0];history=[]
        if has_archive(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute('SELECT id,created_at,old_facts,new_facts FROM daily_control_fact_replacements WHERE employee_id=%s AND report_date=%s ORDER BY id',(row['employee_id'],row['report_date']))
                history=cur.fetchall()
        return dict(fact=row,replacement_history=history)


def upload_report(content,filename,employee_id=None,target=None):
    if not content or len(content)>10*1024*1024:raise ValueError('Размер файла: от 1 байта до 10 МБ')
    name=Path((filename or '').replace(chr(92),'/')).name
    if not name.lower().endswith('.docx') or name.startswith('~$'):raise ValueError('Выберите один Word-отчёт .docx')
    stream=BytesIO(content);stream.name=name
    document=read_document(stream);report=prepare_report(document)
    if target is not None and str(report.get('report_date'))!=str(target):
        raise ValueError('Дата отчёта '+str(report.get('report_date') or 'не определена')+' не совпадает с выбранным днём '+str(target))
    if employee_id is not None and report.get('employee_id') and report['employee_id']!=employee_id:
        raise ValueError('Отчёт относится к другому сотруднику: '+str(report.get('full_name')))
    employee_id=employee_id or report.get('employee_id')
    target=target or report.get('report_date')
    digest=sha256(content).hexdigest()
    with get_connection() as conn:
        ensure_current_source(conn,digest)
        if employee_id is not None and not conn.execute('SELECT 1 FROM employees WHERE id=%s',(employee_id,)).fetchone():raise ValueError('Сотрудник не найден')
        saved=read(conn,'r.source_sha256=%s',(digest,))
        if saved and any((employee_id is not None and r['employee_id']!=employee_id) or (target is not None and str(r['report_date'])!=str(target)) for r in saved):
            raise ValueError('Сохранённый источник относится к другому сотруднику или дате')
        candidates=read(conn,'r.employee_id=%s AND r.report_date=%s',(employee_id,target))
        report['review_options']=report_review.options(conn,digest,document)
    folder=Path(__file__).resolve().parents[2]/'uploads'/'matrix_reports'/digest
    folder.mkdir(parents=True,exist_ok=True);path=folder/name
    if not path.exists():path.write_bytes(content)
    report.update(source_path=str(path),control_saved=bool(saved),control_results=saved)
    if employee_id and target:report['matrix_context']=dict(employee_id=employee_id,date=str(target))
    return dict(report=report,candidates=candidates)


def replacement_preview(conn,request,result,digest):
    if not request.replace_fact_id:return None
    if not has_archive(conn):raise ValueError('История замен ещё не подготовлена')
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT * FROM daily_control_results WHERE id=%s FOR UPDATE',(request.replace_fact_id,))
        target=cur.fetchone()
        if not target:raise DirectoryConflict('Заменяемый факт уже отсутствует. Обновите матрицу.')
        old_digest=target['source_sha256'].strip()
        if not request.replace_source_sha256 or old_digest!=request.replace_source_sha256:
            raise DirectoryConflict('Исходная версия изменилась. Заново проверьте источник.')
        if old_digest==digest:raise ValueError('Этот файл уже подтверждён; замена не требуется')
        if target['employee_id']!=request.expected_employee_id or str(target['report_date'])!=str(request.expected_report_date):
            raise ValueError('Заменять можно только отчёт выбранного сотрудника за выбранный день')
        cur.execute('SELECT * FROM daily_control_results WHERE source_sha256=%s AND employee_id=%s AND report_date=%s ORDER BY id FOR UPDATE',(old_digest,target['employee_id'],target['report_date']))
        old=cur.fetchall();ids=[r['id'] for r in old]
        cur.execute('SELECT * FROM production_matrix_overrides WHERE fact_id=ANY(%s) ORDER BY id FOR UPDATE',(ids,))
        overrides=cur.fetchall()
    old=read(conn,'r.id=ANY(%s)',(ids,))
    from app.repositories import construction_identity as identity
    new=[]
    for fact in result['facts']:
        displayed=identity.describe(conn,dict(fact))
        displayed['category_name']=conn.execute('SELECT name FROM object_categories WHERE id=%s',(fact['category_id'],)).fetchone()[0]
        displayed['po_name']=conn.execute('SELECT name FROM po_types WHERE id=%s',(fact['po_id'],)).fetchone()[0] if fact['po_id'] is not None else None
        new.append(displayed)
    import json
    token=sha256(json.dumps(dict(old=old,new=new,overrides=overrides),sort_keys=True,default=str).encode()).hexdigest()
    return dict(token=token,old_source_sha256=old_digest,old_facts=old,new_facts=new,old_overrides=overrides,
                note='Заменяются все строки выбранного исходного отчёта. Ручные корректировки старых строк будут архивированы.')


def archive_and_replace(conn,preview,request,result,digest,source_name,insert):
    ids=[r['id'] for r in preview['old_facts']]
    conn.execute('DELETE FROM production_matrix_overrides WHERE fact_id=ANY(%s)',(ids,))
    conn.execute('DELETE FROM daily_control_results WHERE id=ANY(%s)',(ids,))
    with conn.cursor() as cursor:
        rows=[insert(cursor,result['report_date'],fact,source_name,digest) for fact in result['facts']]
    if any(not r['created'] for r in rows):raise DirectoryConflict('Данные совпали с другим подтверждённым фактом. Замена отменена.')
    import json
    serial=lambda value:Jsonb(json.loads(json.dumps(value,default=str)))
    conn.execute('''INSERT INTO daily_control_fact_replacements(employee_id,report_date,old_source_sha256,new_source_sha256,old_facts,old_overrides,new_facts)
        VALUES(%s,%s,%s,%s,%s,%s,%s)''',(request.expected_employee_id,result['report_date'],preview['old_source_sha256'],digest,
        serial(preview['old_facts']),serial(preview['old_overrides']),serial(rows)))
    return rows

def delete_fact(fact_id, employee_id, target, source_sha256):
    """Delete exactly one selected fact, preserving its source and corrections in audit."""
    import json
    with get_connection() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT * FROM daily_control_results WHERE id=%s FOR UPDATE',(fact_id,))
            fact=cur.fetchone()
            if not fact:raise DirectoryConflict('Факт уже удалён. Обновите матрицу.')
            if fact['employee_id']!=employee_id or str(fact['report_date'])!=str(target) or fact['source_sha256'].strip()!=source_sha256:
                raise DirectoryConflict('Источник или выбранный день изменился. Обновите матрицу.')
            cur.execute('SELECT * FROM production_matrix_overrides WHERE fact_id=%s ORDER BY id FOR UPDATE',(fact_id,))
            overrides=cur.fetchall()
        serial=lambda value:Jsonb(json.loads(json.dumps(value,default=str)))
        conn.execute('INSERT INTO daily_control_fact_deletions(fact_id,employee_id,report_date,fact,overrides) VALUES(%s,%s,%s,%s,%s)',
                     (fact_id,employee_id,target,serial(read(conn,'r.id=%s',(fact_id,))[0]),serial(overrides)))
        conn.execute('DELETE FROM production_matrix_overrides WHERE fact_id=%s',(fact_id,))
        conn.execute('DELETE FROM daily_control_results WHERE id=%s',(fact_id,))
    return dict(deleted_fact_id=fact_id,employee_id=employee_id,date=str(target))
