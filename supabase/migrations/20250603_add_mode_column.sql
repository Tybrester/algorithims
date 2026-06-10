-- Add mode column to options_trades for chop/trend tracking
ALTER TABLE options_trades
ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'trend' CHECK (mode IN ('chop', 'trend', 'neutral'));

-- Create index for fast filtering
CREATE INDEX IF NOT EXISTS idx_options_trades_mode ON options_trades(mode);
