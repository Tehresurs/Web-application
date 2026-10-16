ALTER TABLE positions ADD COLUMN IF NOT EXISTS planned_count INTEGER NOT NULL DEFAULT 0
    CONSTRAINT positions_planned_count_nonnegative CHECK (planned_count >= 0);
