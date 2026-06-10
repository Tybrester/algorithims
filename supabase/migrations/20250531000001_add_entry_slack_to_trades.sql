-- Add entry_slack column to options_trades for slack bucket analysis
ALTER TABLE options_trades 
ADD COLUMN IF NOT EXISTS entry_slack NUMERIC DEFAULT NULL;

COMMENT ON COLUMN options_trades.entry_slack IS 'Slack value (wick rejection strength in ATR units) at trade entry for Boof 22/23';

-- Create index for faster slack-based queries
CREATE INDEX IF NOT EXISTS idx_options_trades_entry_slack 
ON options_trades(entry_slack) 
WHERE entry_slack IS NOT NULL;
