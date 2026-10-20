"""Step 37 ONLY: install into owned isolated clone, never production."""
import hashlib,hmac
from psycopg import sql
from scripts.dk_service_prototype import SOURCE,TABLES

def install(c,owner,caller):
 if not c.info.dbname.startswith('auth_stage3_tx_'):raise RuntimeError('Isolated transaction clone required')
 # Existing private schema/key/context are inherited from the isolated prototype.
 c.execute('CREATE TABLE dk_service.tx_state(xid bigint PRIMARY KEY, nonce uuid NOT NULL, sealed boolean NOT NULL DEFAULT false, context text, keys text[])')
 c.execute(sql.SQL('ALTER TABLE dk_service.tx_state OWNER TO {}').format(sql.Identifier(owner)))
 c.execute("""CREATE FUNCTION dk_service.touch() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,dk_service,pg_temp AS $$
 BEGIN
  IF session_user<>TG_ARGV[0] THEN RETURN NULL; END IF;
  IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Unsupported isolation' USING ERRCODE='42501'; END IF;
  PERFORM pg_advisory_xact_lock(20261017,29);
  IF EXISTS(SELECT 1 FROM dk_service.tx_state WHERE xid=txid_current() AND sealed) THEN RAISE EXCEPTION 'Calendar sealed' USING ERRCODE='42501'; END IF;
  INSERT INTO dk_service.tx_state(xid,nonce) VALUES(txid_current(),gen_random_uuid())
   ON CONFLICT(xid) DO UPDATE SET nonce=gen_random_uuid(),context=NULL,keys=NULL;
  RETURN NULL;
 END $$""")
 # Statement-level BEFORE lock serializes candidate writes BEFORE source mutation.
 for table in TABLES[:-1]:
  c.execute(sql.SQL('CREATE TRIGGER aaa_tx_dk_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON {}.{} FOR EACH STATEMENT EXECUTE FUNCTION dk_service.touch({})').format(sql.Identifier(SOURCE),sql.Identifier(table),sql.Literal(caller)))
 c.execute("""CREATE FUNCTION dk_service.tx_context() RETURNS text LANGUAGE SQL VOLATILE
 SET search_path=pg_catalog,dk_service,pg_temp AS $$
 SELECT 'dk37|'||current_database()||'|'||dk_service.context()||'|'||nonce::text FROM dk_service.tx_state WHERE xid=txid_current()
 $$""")
 c.execute("""CREATE FUNCTION dk_service.tx_snapshot() RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,dk_service,pg_temp SET timezone='UTC' SET datestyle='ISO,YMD' AS $$
 DECLARE snap jsonb;
 BEGIN
  snap:=dk_service.snapshot();
  INSERT INTO dk_service.tx_state(xid,nonce) VALUES(txid_current(),gen_random_uuid()) ON CONFLICT DO NOTHING;
  IF EXISTS(SELECT 1 FROM dk_service.tx_state WHERE xid=txid_current() AND sealed) THEN RAISE EXCEPTION 'Already sealed' USING ERRCODE='42501'; END IF;
  RETURN jsonb_build_object('context',dk_service.tx_context(),'events',snap->'events');
 END $$""")
 c.execute("""CREATE FUNCTION dk_service.register_intent(keys text[],proof bytea) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,dk_service,pg_temp SET timezone='UTC' SET datestyle='ISO,YMD' AS $$
 DECLARE ctx text; payload text; expected bytea; secret bytea; diff integer:=0; i integer;
 BEGIN
  ctx:=dk_service.tx_snapshot()->>'context';
  IF keys IS NULL OR proof IS NULL OR octet_length(proof)<>32 OR cardinality(keys)>100000 THEN RAISE EXCEPTION 'Proof rejected' USING ERRCODE='42501'; END IF;
  IF EXISTS(SELECT 1 FROM unnest(keys) k WHERE k IS NULL OR k !~ '^[1-9][0-9]*:[0-9]{4}-[0-9]{2}-[0-9]{2}$') THEN RAISE EXCEPTION 'Proof rejected' USING ERRCODE='42501'; END IF;
  SELECT ctx||'|'||coalesce(string_agg(k,',' ORDER BY k COLLATE pg_catalog."C"),'') INTO payload FROM unnest(keys) k;
  SELECT s.secret INTO secret FROM dk_service.signing_key s WHERE id=1;
  IF secret IS NULL OR octet_length(secret)<>32 THEN RAISE EXCEPTION 'Key unavailable' USING ERRCODE='42501'; END IF;
  expected:=dk_service.hmac(convert_to(payload,'UTF8'),secret,'sha256');
  IF expected IS NULL THEN RAISE EXCEPTION 'Proof rejected' USING ERRCODE='42501'; END IF;
  FOR i IN 0..31 LOOP diff:=diff | (get_byte(expected,i) # get_byte(proof,i)); END LOOP;
  IF diff<>0 THEN RAISE EXCEPTION 'Proof rejected' USING ERRCODE='42501'; END IF;
  UPDATE dk_service.tx_state SET context=ctx,keys=register_intent.keys WHERE xid=txid_current();
 END $$""")
 c.execute("""CREATE FUNCTION dk_service.finish() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,dk_service,pg_temp SET timezone='UTC' SET datestyle='ISO,YMD' AS $$
 DECLARE st dk_service.tx_state%ROWTYPE;
 BEGIN
  PERFORM pg_advisory_xact_lock(20261017,29);
  SELECT * INTO st FROM dk_service.tx_state WHERE xid=txid_current() FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Missing state' USING ERRCODE='42501'; END IF;
  IF st.sealed THEN RETURN NULL; END IF;
  IF st.context IS NULL OR st.keys IS NULL OR st.context IS DISTINCT FROM dk_service.tx_context() THEN RAISE EXCEPTION 'Missing or stale intent' USING ERRCODE='42501'; END IF;
  UPDATE dk_service.tx_state SET sealed=true WHERE xid=txid_current();
  DELETE FROM test_construction_identity_stage46.production_matrix_dk d WHERE d.employee_id::text||':'||d.work_date::text=ANY(st.keys);
  RETURN NULL;
 END $$""")
 for name,args in [('touch',''),('tx_context',''),('tx_snapshot',''),('register_intent','text[],bytea'),('finish','')]:
  c.execute(sql.SQL('ALTER FUNCTION dk_service.'+name+'('+args+') OWNER TO {}').format(sql.Identifier(owner)))
 c.execute('CREATE CONSTRAINT TRIGGER dk_finish AFTER INSERT OR UPDATE ON dk_service.tx_state DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dk_service.finish()')
 c.execute('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dk_service FROM PUBLIC')
 # The previous prune is NOT an alternative entry point in this clone.
 c.execute(sql.SQL('REVOKE EXECUTE ON FUNCTION dk_service.prune(text[],bytea),dk_service.snapshot() FROM {}').format(sql.Identifier(caller)))
 for sig in ['tx_snapshot()','register_intent(text[],bytea)']:
  c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION dk_service.'+sig+' TO {}').format(sql.Identifier(caller)))

def prepare(conn,key):
 from datetime import date
 from app.services.matrix_dk import eligible
 # A trusted context, including explicit pg_temp LAST, for all canonical reads.
 original=conn.execute('SHOW search_path').fetchone()[0]
 conn.execute("SET LOCAL search_path=pg_catalog,test_construction_identity_stage46,pg_temp")
 try:
  snap=conn.execute('SELECT dk_service.tx_snapshot()').fetchone()[0]
  keys=sorted(str(e['employee_id'])+':'+e['date'] for e in snap['events'] if not eligible(conn,e['employee_id'],date.fromisoformat(e['date'])))
  return keys,hmac.new(key,(snap['context']+'|'+','.join(keys)).encode(),hashlib.sha256).digest()
 finally:
  from psycopg.pq import TransactionStatus
  if conn.info.transaction_status==TransactionStatus.INTRANS:
   conn.execute("SELECT set_config('search_path',%s,true)",(original,))

def register(conn,key):
 keys,proof=prepare(conn,key)
 conn.execute('SELECT dk_service.register_intent(%s,%s)',(keys,proof))
 return keys
