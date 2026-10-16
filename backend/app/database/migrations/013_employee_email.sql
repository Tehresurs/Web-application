-- Optional contact detail; existing employees remain unchanged.
ALTER TABLE employees ADD COLUMN IF NOT EXISTS email TEXT;
