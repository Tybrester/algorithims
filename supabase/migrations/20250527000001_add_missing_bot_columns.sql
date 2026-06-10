-- Add missing columns to options_bots table
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS reset_at TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS take_profit_pct NUMERIC DEFAULT 35;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS stop_loss_pct NUMERIC DEFAULT 18;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS paper_balance NUMERIC DEFAULT 100000;

-- Add missing columns to stock_bots table
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS reset_at TIMESTAMPTZ DEFAULT NULL;
