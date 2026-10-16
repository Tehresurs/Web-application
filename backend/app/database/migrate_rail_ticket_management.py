from pathlib import Path
from app.database.db import get_connection


def migrate():
    with get_connection() as conn:
        conn.execute((Path(__file__).with_name('migrations')/'015_rail_ticket_management.sql').read_text(encoding='utf-8'))


if __name__ == '__main__':
    migrate()
    print('Migration 015 applied')
