def policy(conn, employee_id, lock=False):
    # Legacy isolated schemas can still read/use the original two modes.
    with conn.cursor() as cur:
        if lock:
            cur.execute('SELECT id FROM employees WHERE id=%s FOR SHARE',(employee_id,))
            cur.fetchone()
        cur.execute("SELECT to_regclass('production_control_mode_positions')")
        installed=cur.fetchone()[0] is not None
        geodetic=False
        if installed:
            cur.execute('''SELECT 1 FROM employees e JOIN production_control_mode_positions p
                ON p.position_id=e.position_id WHERE e.id=%s'''+(' FOR SHARE OF p' if lock else ''),(employee_id,))
            geodetic=cur.fetchone() is not None
    return dict(allowed_control_modes=['INSPECTION','OPERATIONAL']+(['GEODETIC'] if geodetic else []),
                default_control_mode='GEODETIC' if geodetic else 'INSPECTION')


def validate_mode(mode, rules):
    if mode is not None and mode not in rules['allowed_control_modes']:
        raise ValueError('Режим контроля недоступен для должности сотрудника')
