-- Stage 1 only. No runtime authentication wiring or real accounts.
DO $$ BEGIN
 IF current_database() <> 'ai_excel_agent_test' OR current_schema() <> 'test_construction_identity_stage46' THEN
  RAISE EXCEPTION 'Wrong database/schema for auth stage 1';
 END IF;
END $$;
CREATE TABLE auth_users (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 login text NOT NULL UNIQUE CHECK (login=lower(btrim(login)) AND length(login) BETWEEN 3 AND 254),
 employee_id bigint UNIQUE REFERENCES employees(id) ON DELETE RESTRICT,
 password_hash text CHECK (password_hash IS NULL OR length(btrim(password_hash))>0),
 is_blocked boolean NOT NULL DEFAULT true,
 blocked_at timestamptz,
 blocked_reason text,
 credential_version integer NOT NULL DEFAULT 1 CHECK (credential_version>0),
 created_at timestamptz NOT NULL DEFAULT now(),
 password_changed_at timestamptz,
 CHECK (is_blocked OR password_hash IS NOT NULL),
 CHECK (is_blocked OR (blocked_at IS NULL AND blocked_reason IS NULL))
);
CREATE TABLE auth_roles (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 code text NOT NULL UNIQUE CHECK (code ~ '^[A-Z][A-Z0-9_]*$'),
 description text NOT NULL
);
CREATE TABLE auth_permissions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 code text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_]*[.][a-z][a-z0-9_]*$'),
 description text NOT NULL
);
CREATE TABLE auth_user_roles (
 user_id bigint NOT NULL REFERENCES auth_users(id) ON DELETE RESTRICT,
 role_id bigint NOT NULL REFERENCES auth_roles(id) ON DELETE RESTRICT,
 PRIMARY KEY(user_id,role_id)
);
CREATE TABLE auth_role_permissions (
 role_id bigint NOT NULL REFERENCES auth_roles(id) ON DELETE RESTRICT,
 permission_id bigint NOT NULL REFERENCES auth_permissions(id) ON DELETE RESTRICT,
 PRIMARY KEY(role_id,permission_id)
);
CREATE TABLE auth_sessions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 user_id bigint NOT NULL REFERENCES auth_users(id) ON DELETE RESTRICT,
 token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
 credential_version integer NOT NULL CHECK (credential_version>0),
 created_at timestamptz NOT NULL DEFAULT now(),
 last_seen_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 revoked_at timestamptz,
 revoked_reason text,
 CHECK (expires_at>created_at),
 CHECK (last_seen_at>=created_at AND last_seen_at<=expires_at),
 CHECK (revoked_at IS NULL OR revoked_at>=created_at),
 CHECK (revoked_at IS NOT NULL OR revoked_reason IS NULL)
);
CREATE INDEX auth_sessions_user_idx ON auth_sessions(user_id);
CREATE INDEX auth_sessions_active_expiry_idx ON auth_sessions(expires_at) WHERE revoked_at IS NULL;
CREATE TABLE auth_security_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 occurred_at timestamptz NOT NULL DEFAULT now(),
 actor_user_id bigint REFERENCES auth_users(id) ON DELETE RESTRICT,
 subject_user_id bigint REFERENCES auth_users(id) ON DELETE RESTRICT,
 event_type text NOT NULL CHECK (event_type ~ '^[A-Z][A-Z0-9_]*$'),
 outcome text NOT NULL CHECK (outcome IN ('SUCCESS','DENIED','ERROR')),
 request_id uuid,
 details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details)='object')
);
CREATE INDEX auth_security_events_time_idx ON auth_security_events(occurred_at);
CREATE INDEX auth_security_events_subject_idx ON auth_security_events(subject_user_id,occurred_at);
INSERT INTO auth_roles(code,description) VALUES
 ('SYSTEM_TECHNICIAN','View all production data, create, edit and export Excel'),
 ('OFFICE_MANAGER','View all production data and export Excel');
INSERT INTO auth_permissions(code,description) VALUES
 ('data.read','View all production sections and data'),
 ('data.create','Create production data; excludes settings, users and workflow decisions'),
 ('data.update','Edit production data; excludes settings, users and workflow decisions'),
 ('excel.export','Export Excel; does not grant report publication or workflow changes');
INSERT INTO auth_role_permissions(role_id,permission_id)
 SELECT r.id,p.id FROM auth_roles r CROSS JOIN auth_permissions p
 WHERE r.code='SYSTEM_TECHNICIAN' OR (r.code='OFFICE_MANAGER' AND p.code IN ('data.read','excel.export'));
-- No grants on production objects and no global PostgreSQL role changes.
REVOKE ALL ON auth_users,auth_roles,auth_permissions,auth_user_roles,auth_role_permissions,auth_sessions,auth_security_events FROM PUBLIC;
REVOKE ALL ON SEQUENCE auth_users_id_seq,auth_roles_id_seq,auth_permissions_id_seq,auth_sessions_id_seq,auth_security_events_id_seq FROM PUBLIC;
