"""Step 42 isolated-only closed writes; never imported by runtime."""
from psycopg import sql
from scripts.dk_service_prototype import SOURCE,TABLES

def install(c,caller,password,owner,dk_owner,fixture):
 if not c.info.dbname.startswith('auth_stage3_tx_closed_'):raise RuntimeError('Own closed clone required')
 for role,login in [(caller,'LOGIN'),(owner,'NOLOGIN')]:
  c.execute(sql.SQL('CREATE ROLE {} '+login+' NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(sql.Identifier(role)))
 # Parameters stay in memory; no SQL/password printed or persisted in artifacts.
 c.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(caller),sql.Literal(password)))
 c.execute(sql.SQL('REVOKE CONNECT,TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(c.info.dbname)))
 c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(c.info.dbname),sql.Identifier(caller)))
 c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(c.info.dbname),sql.Identifier(fixture)))
 c.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {},{}').format(sql.Identifier(SOURCE),sql.Identifier(caller),sql.Identifier(owner)))
 for table in TABLES+('crews','construction_objects','construction_entities','construction_entity_hierarchy','construction_subobjects','construction_entity_current'):
  c.execute(sql.SQL('GRANT SELECT ON {}.{} TO {}').format(sql.Identifier(SOURCE),sql.Identifier(table),sql.Identifier(caller)))
 for table in ['employees','crews','rail_tickets','construction_objects','construction_entities','construction_entity_hierarchy','construction_subobjects','construction_entity_current']:
  c.execute(sql.SQL('GRANT SELECT ON {}.{} TO {}').format(sql.Identifier(SOURCE),sql.Identifier(table),sql.Identifier(owner)))
 c.execute(sql.SQL('GRANT UPDATE(full_name,crew_id,updated_at) ON {}.employees TO {}').format(sql.Identifier(SOURCE),sql.Identifier(owner)))
 c.execute(sql.SQL('GRANT INSERT(file_hash,source_filename,employee_id,status),UPDATE(object_id,entity_id,updated_at) ON {}.rail_tickets TO {}').format(sql.Identifier(SOURCE),sql.Identifier(owner)))
 sequence=c.execute("SELECT pg_get_serial_sequence(%s,'id')",(SOURCE+'.rail_tickets',)).fetchone()[0]
 c.execute(sql.SQL('GRANT USAGE ON SEQUENCE {} TO {}').format(sql.SQL(sequence),sql.Identifier(owner)))
 for sig in ['normalize_known_value(text,text)','construction_reference(bigint,bigint,bigint)']:
  c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+SOURCE+'.'+sig+' TO {},{}').format(sql.Identifier(owner),sql.Identifier(caller)))
 # The protected state must recognize the new session_user; no fixture bypass is added.
 for table in TABLES[:-1]:
  c.execute(sql.SQL('DROP TRIGGER aaa_tx_dk_guard ON {}.{}').format(sql.Identifier(SOURCE),sql.Identifier(table)))
  c.execute(sql.SQL('CREATE TRIGGER aaa_tx_dk_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON {}.{} FOR EACH STATEMENT EXECUTE FUNCTION dk_service.touch({})').format(sql.Identifier(SOURCE),sql.Identifier(table),sql.Literal(caller)))
 c.execute(sql.SQL('GRANT USAGE ON SCHEMA dk_service TO {}').format(sql.Identifier(caller)))
 for sig in ['tx_snapshot()','register_intent(text[],bytea)']:
  c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION dk_service.'+sig+' TO {}').format(sql.Identifier(caller)))
 # Remove all advisory capabilities through PUBLIC IN THIS DATABASE ONLY.
 signatures=c.execute("SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='pg_catalog' AND p.proname LIKE 'pg_%advisory%'").fetchall()
 for (sig,) in signatures:
  c.execute(sql.SQL('REVOKE ALL ON FUNCTION '+sig+' FROM PUBLIC'))
 c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION pg_catalog.pg_advisory_xact_lock(integer,integer) TO {},{},{}').format(sql.Identifier(owner),sql.Identifier(dk_owner),sql.Identifier(fixture)))
 c.execute(sql.SQL('CREATE SCHEMA closed_write AUTHORIZATION {}').format(sql.Identifier(owner)))
 c.execute('REVOKE ALL ON SCHEMA closed_write FROM PUBLIC')
 c.execute(sql.SQL('GRANT USAGE ON SCHEMA closed_write TO {}').format(sql.Identifier(caller)))
 c.execute("""CREATE FUNCTION closed_write.enter() RETURNS void LANGUAGE plpgsql
 SET search_path=pg_catalog,closed_write,pg_temp AS $$ BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Unsupported isolation' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(20261017,29);
 PERFORM pg_advisory_xact_lock(20261007,1601);
 PERFORM pg_advisory_xact_lock(20261013,24);
 END $$""")
 bodies={
 'employee(bigint,text)':("employee_id bigint,new_name text", """PERFORM closed_write.enter();
 IF new_name IS NULL OR btrim(new_name)='' OR length(new_name)>200 THEN RAISE EXCEPTION 'Invalid name' USING ERRCODE='22023'; END IF;
 PERFORM id FROM test_construction_identity_stage46.employees WHERE id=employee_id FOR SHARE;
 UPDATE test_construction_identity_stage46.employees SET full_name=new_name,updated_at=now() WHERE id=employee_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Employee missing' USING ERRCODE='P0002'; END IF;"""),
 'crew(bigint,bigint)':("employee_id bigint,target_crew bigint", """PERFORM closed_write.enter();
 IF target_crew IS NOT NULL THEN
 PERFORM id FROM test_construction_identity_stage46.crews WHERE id=target_crew;
 IF NOT FOUND THEN RAISE EXCEPTION 'Crew missing' USING ERRCODE='P0002'; END IF;
 END IF;
 PERFORM id FROM test_construction_identity_stage46.employees WHERE id=employee_id FOR UPDATE;
 UPDATE test_construction_identity_stage46.employees SET crew_id=target_crew,updated_at=now() WHERE id=employee_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Employee missing' USING ERRCODE='P0002'; END IF;"""),
 'ticket(text,bigint)':("file_digest text,employee_id bigint", """PERFORM closed_write.enter();
 INSERT INTO test_construction_identity_stage46.rail_tickets(file_hash,source_filename,employee_id,status)
 VALUES(file_digest,'closed-isolated.pdf',employee_id,'PARSED');"""),
 'ticket_object(bigint,bigint)':("ticket_id bigint,target_object bigint", """PERFORM closed_write.enter();
 PERFORM id FROM test_construction_identity_stage46.rail_tickets WHERE id=ticket_id FOR UPDATE;
 UPDATE test_construction_identity_stage46.rail_tickets SET object_id=target_object,entity_id=NULL,updated_at=now() WHERE id=ticket_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Ticket missing' USING ERRCODE='P0002'; END IF;""")}
 for sig,(args,body) in bodies.items():
  name=sig.split('(')[0]
  c.execute('CREATE FUNCTION closed_write.'+name+'('+args+') RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,closed_write,test_construction_identity_stage46,pg_temp AS $$ BEGIN '+body+' END $$')
 for sig in ['enter()']+list(bodies):
  c.execute(sql.SQL('ALTER FUNCTION closed_write.'+sig+' OWNER TO {}').format(sql.Identifier(owner)))
 c.execute('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA closed_write FROM PUBLIC')
 for sig in bodies:c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION closed_write.'+sig+' TO {}').format(sql.Identifier(caller)))
 return {'advisory_signatures_revoked':len(signatures),'operations':list(bodies),'owner':owner,'caller':caller}
