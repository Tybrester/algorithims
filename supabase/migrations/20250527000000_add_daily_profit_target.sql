-- Add daily_profit_target column to options_bots table
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS daily_profit_target NUMERIC DEFAULT NULL;

-- Add comment explaining the column
COMMENT ON COLUMN options_bots.daily_profit_target IS 'Daily profit target in dollars. Bot stops taking new trades once daily realized P&L reaches this amount.';
