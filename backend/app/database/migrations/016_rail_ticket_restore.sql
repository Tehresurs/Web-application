-- Keep the exact previous state; never infer it for legacy annulled tickets.
ALTER TABLE rail_tickets ADD COLUMN IF NOT EXISTS annul_snapshot JSONB;
