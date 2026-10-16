"""Atomic changes to the existing employee-to-crew link only."""
from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound


def change_memberships(target_crew_id, employees, confirm_transfers=False):
    expected = {item['employee_id']: item['expected_crew_id'] for item in employees}
    if not expected or len(expected) != len(employees):
        raise ValueError('Выберите сотрудников без повторений')
    with get_connection() as conn:
        with conn.transaction():
            if target_crew_id is not None:
                if not conn.execute('SELECT id FROM crews WHERE id=%s FOR KEY SHARE', (target_crew_id,)).fetchone():
                    raise DirectoryNotFound('Экипаж не найден')
            rows = conn.execute('SELECT id, crew_id FROM employees WHERE id = ANY(%s) ORDER BY id FOR UPDATE',
                                (sorted(expected),)).fetchall()
            if len(rows) != len(expected):
                raise DirectoryNotFound('Один из сотрудников не найден. Обновите список')
            if any(old != expected[employee_id] for employee_id, old in rows):
                raise DirectoryConflict('Закрепление сотрудника изменилось. Обновите список и повторите выбор')
            if not confirm_transfers and any(old is not None and target_crew_id is not None and old != target_crew_id for _, old in rows):
                raise DirectoryConflict('Для перевода из другого экипажа необходимо явное подтверждение')
            conn.execute('UPDATE employees SET crew_id=%s WHERE id = ANY(%s)', (target_crew_id, sorted(expected)))
    return [{'employee_id': employee_id, 'crew_id': target_crew_id} for employee_id, _ in rows]
