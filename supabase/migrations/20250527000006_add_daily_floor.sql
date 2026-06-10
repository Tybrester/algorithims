-- Add daily profit target column to options_bots
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_profit_target NUMERIC DEFAULT NULL;

-- Add daily floor columns to options_bots
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_floor_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_floor_amount NUMERIC DEFAULT 0;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_floor_triggered BOOLEAN DEFAULT FALSE;

-- Add same columns to stock_bots
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS daily_profit_target NUMERIC DEFAULT NULL;
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS daily_floor_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS daily_floor_amount NUMERIC DEFAULT 0;
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS daily_floor_triggered BOOLEAN DEFAULT FALSE;

-- Migrate existing trailing stop data to floor (optional - uncomment if you want to migrate)
-- UPDATE options_bots SET daily_floor_enabled = daily_trailing_stop_enabled WHERE daily_trailing_stop_enabled IS NOT NULL;
-- UPDATE options_bots SET daily_floor_amount = daily_trailing_stop_amount WHERE daily_trailing_stop_amount IS NOT NULL;
