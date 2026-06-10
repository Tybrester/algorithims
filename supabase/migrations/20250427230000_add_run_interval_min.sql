-- Add run_interval_min column to stock_bots table
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS run_interval_min INTEGER DEFAULT 15;
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMPTZ;

-- Add comment explaining the column
COMMENT ON COLUMN stock_bots.run_interval_min IS 'How often the bot runs in minutes (e.g., 1, 5, 15, 30, 60)';
COMMENT ON COLUMN stock_bots.last_run_at IS 'Last time the bot was executed';

-- Update existing bots with proper intervals based on their names
UPDATE stock_bots SET run_interval_min = 1 WHERE name ILIKE '%1%' AND name ILIKE '%min%' AND run_interval_min = 15;
UPDATE stock_bots SET run_interval_min = 5 WHERE name ILIKE '%5%' AND run_interval_min = 15;
UPDATE stock_bots SET run_interval_min = 10 WHERE name ILIKE '%10%' AND run_interval_min = 15;
UPDATE stock_bots SET run_interval_min = 15 WHERE name ILIKE '%15%' AND run_interval_min = 15;
UPDATE stock_bots SET run_interval_min = 30 WHERE name ILIKE '%30%' AND run_interval_min = 15;
UPDATE stock_bots SET run_interval_min = 60 WHERE name ILIKE '%hour%' OR name ILIKE '%60%' AND run_interval_min = 15;

-- Also add to options_bots
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS run_interval_min INTEGER DEFAULT 15;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMPTZ;
