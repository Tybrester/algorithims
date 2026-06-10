-- Add max daily trades columns to options_bots
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS max_daily_trades INTEGER DEFAULT NULL;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_trade_count INTEGER DEFAULT 0;

-- Add same columns to stock_bots
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS max_daily_trades INTEGER DEFAULT NULL;
ALTER TABLE stock_bots ADD COLUMN IF NOT EXISTS daily_trade_count INTEGER DEFAULT 0;
