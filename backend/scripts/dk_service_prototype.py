"""Step 33 experiment only. Never imported by the production connection class."""
import hashlib,hmac
from psycopg import sql
SOURCE='test_construction_identity_stage46'
TABLES=('employees','positions','employee_movements','rail_tickets','employee_sick_periods','employee_luvr_day_overrides','employee_duration_exceptions','employee_absences','production_matrix_dk')

def install(c,owner,caller,key):
    if not c.info.dbname.startswith('auth_stage3_') or len(key)!=32:raise RuntimeError('Own isolated cluster only')
    if c.execute("SELECT EXISTS(SELECT 1 FROM pg_class r JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname=%s AND r.relrowsecurity)",(SOURCE,)).fetchone()[0]:raise RuntimeError('RLS requires separate analysis')
    c.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(sql.Identifier(owner)))
    c.execute(sql.SQL('CREATE SCHEMA dk_service AUTHORIZATION {}').format(sql.Identifier(owner)))
    c.execute('CREATE EXTENSION pgcrypto WITH SCHEMA dk_service')
    c.execute('REVOKE ALL ON SCHEMA dk_service FROM PUBLIC')
    c.execute('CREATE TABLE dk_service.signing_key(id integer PRIMARY KEY CHECK(id=1),secret bytea NOT NULL CHECK(octet_length(secret)=32))')
    c.execute(sql.SQL('ALTER TABLE dk_service.signing_key OWNER TO {}').format(sql.Identifier(owner)))
    c.execute('INSERT INTO dk_service.signing_key VALUES (1,%s)',(key,))
    c.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(SOURCE),sql.Identifier(owner)))
    for table in TABLES:c.execute(sql.SQL('GRANT SELECT ON {}.{} TO {}').format(sql.Identifier(SOURCE),sql.Identifier(table),sql.Identifier(owner)))
    c.execute(sql.SQL('GRANT UPDATE(work_date),DELETE ON {}.production_matrix_dk TO {}').format(sql.Identifier(SOURCE),sql.Identifier(owner)))
    parts=[]
    for table in TABLES:
        parts.append("pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(coalesce((SELECT string_agg(to_jsonb(t)::text,E'\\n' ORDER BY to_jsonb(t)::text COLLATE pg_catalog.\"C\") FROM "+SOURCE+'.'+table+" t),''),'UTF8')),'hex')")
    # All table names are fixed constants; no caller-controlled dynamic SQL.
    fingerprint="pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to("+"||'|'||".join(parts)+",'UTF8')),'hex')"
    fingerprint=fingerprint.replace('\"','"')
    c.execute("CREATE FUNCTION dk_service.context() RETURNS text LANGUAGE SQL VOLATILE SET search_path=pg_catalog,dk_service,pg_temp SET timezone='UTC' SET datestyle='ISO,YMD' AS $$ SELECT pg_backend_pid()::text||'|'||txid_current()::text||'|'||"+fingerprint+' $$')
    c.execute("""CREATE FUNCTION dk_service.snapshot() RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,dk_service,pg_temp SET timezone='UTC' SET datestyle='ISO,YMD' AS $$
        DECLARE events jsonb;
        BEGIN
          IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Unsupported maintenance isolation' USING ERRCODE='42501'; END IF;
          PERFORM pg_advisory_xact_lock(20261017,29);
          PERFORM employee_id FROM test_construction_identity_stage46.production_matrix_dk ORDER BY employee_id,work_date FOR UPDATE;
          SELECT coalesce(jsonb_agg(jsonb_build_object('employee_id',employee_id,'date',work_date::text) ORDER BY employee_id,work_date),'[]'::jsonb)
          INTO events FROM test_construction_identity_stage46.production_matrix_dk;
          RETURN jsonb_build_object('context',dk_service.context(),'events',events);
        END $$""")
    c.execute("""CREATE FUNCTION dk_service.prune(keys text[],proof bytea) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,dk_service,pg_temp SET timezone='UTC' SET datestyle='ISO,YMD' AS $$
        DECLARE expected bytea; secret bytea; payload text; context text; difference integer:=0; i integer; removed integer;
        BEGIN
          context:=dk_service.snapshot()->>'context';
          IF keys IS NULL OR proof IS NULL OR octet_length(proof)<>32 OR cardinality(keys)>100000 THEN RAISE EXCEPTION 'Maintenance proof rejected' USING ERRCODE='42501'; END IF;
          IF EXISTS(SELECT 1 FROM unnest(keys) k WHERE k IS NULL OR k !~ '^[1-9][0-9]*:[0-9]{4}-[0-9]{2}-[0-9]{2}$') THEN RAISE EXCEPTION 'Maintenance proof rejected' USING ERRCODE='42501'; END IF;
          SELECT context||'|'||coalesce(string_agg(k,',' ORDER BY k COLLATE pg_catalog."C"),'') INTO payload FROM unnest(keys) k;
          SELECT s.secret INTO secret FROM dk_service.signing_key s WHERE id=1;
          IF secret IS NULL OR octet_length(secret)<>32 THEN RAISE EXCEPTION 'Maintenance key unavailable' USING ERRCODE='42501'; END IF;
          expected:=dk_service.hmac(convert_to(payload,'UTF8'),secret,'sha256');
          IF expected IS NULL OR octet_length(expected)<>32 THEN RAISE EXCEPTION 'Maintenance proof rejected' USING ERRCODE='42501'; END IF;
          FOR i IN 0..31 LOOP difference:=difference | (get_byte(expected,i) # get_byte(proof,i)); END LOOP;
          IF difference<>0 THEN RAISE EXCEPTION 'Maintenance proof rejected' USING ERRCODE='42501'; END IF;
          DELETE FROM test_construction_identity_stage46.production_matrix_dk d WHERE d.employee_id::text||':'||d.work_date::text=ANY(keys);
          GET DIAGNOSTICS removed=ROW_COUNT;
          RETURN removed;
        END $$""")
    for name,arguments in [('context',''),('snapshot',''),('prune','text[],bytea')]:
        c.execute(sql.SQL('ALTER FUNCTION dk_service.'+name+'('+arguments+') OWNER TO {}').format(sql.Identifier(owner)))
    c.execute('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dk_service FROM PUBLIC')
    c.execute('REVOKE ALL ON dk_service.signing_key FROM PUBLIC')
    c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION dk_service.hmac(bytea,bytea,text) TO {}').format(sql.Identifier(owner)))
    c.execute(sql.SQL('GRANT USAGE ON SCHEMA dk_service TO {}').format(sql.Identifier(caller)))
    for signature in ['snapshot()','prune(text[],bytea)']:c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION dk_service.'+signature+' TO {}').format(sql.Identifier(caller)))

def prepare(conn,key):
    from datetime import date
    from app.services.matrix_dk import eligible
    snap=conn.execute('SELECT dk_service.snapshot()').fetchone()[0]
    keys=sorted(str(e['employee_id'])+':'+e['date'] for e in snap['events'] if not eligible(conn,e['employee_id'],date.fromisoformat(e['date'])))
    proof=hmac.new(key,(snap['context']+'|'+','.join(keys)).encode(),hashlib.sha256).digest()
    return keys,proof

def reconcile(conn,key):
    keys,proof=prepare(conn,key)
    return conn.execute('SELECT dk_service.prune(%s,%s)',(keys,proof)).fetchone()[0]
