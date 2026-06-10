-- Add daily trailing stop columns to options_bots
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_trailing_stop_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_trailing_stop_amount DECIMAL(12,2) DEFAULT 350;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_peak_pnl DECIMAL(12,2) DEFAULT 0;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_trailing_stop_triggered BOOLEAN DEFAULT FALSE;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_reset_date DATE DEFAULT NULL;

-- Add same columns to stock_bots
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS daily_trailing_stop_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS daily_trailing_stop_amount DECIMAL(12,2) DEFAULT 350;
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS daily_peak_pnl DECIMAL(12,2) DEFAULT 0;
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS daily_trailing_stop_triggered BOOLEAN DEFAULT FALSE;
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS daily_reset_date DATE DEFAULT NULL;
