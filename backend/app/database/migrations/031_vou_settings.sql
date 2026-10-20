-- VOU requisites only; no updates to matrix/report source tables.
CREATE TABLE IF NOT EXISTS vou_settings (
 id integer PRIMARY KEY CHECK (id=1),
 contract_number text NOT NULL DEFAULT '',
 contract_date date,
 contract_revision text NOT NULL DEFAULT '',
 customer_signer_name text NOT NULL DEFAULT '',
 contractor_signer_name text NOT NULL DEFAULT '',
 updated_at timestamptz NOT NULL DEFAULT now()
);
