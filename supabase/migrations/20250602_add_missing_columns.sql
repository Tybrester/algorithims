-- Add missing columns to symbol_slack_scores

ALTER TABLE symbol_slack_scores 
ADD COLUMN IF NOT EXISTS bot_id uuid REFERENCES options_bots(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS losing_trades int DEFAULT 0,
ADD COLUMN IF NOT EXISTS daily_pnl decimal(12,2) DEFAULT 0,
ADD COLUMN IF NOT EXISTS daily_trades int DEFAULT 0,
ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

-- Update unique constraint to include bot_id
ALTER TABLE symbol_slack_scores 
DROP CONSTRAINT IF EXISTS symbol_slack_scores_symbol_user_id_bot_signal_key;

ALTER TABLE symbol_slack_scores 
ADD CONSTRAINT symbol_slack_scores_symbol_user_id_bot_signal_key 
UNIQUE(symbol, user_id, bot_id, bot_signal);

-- Index for bot lookups
CREATE INDEX IF NOT EXISTS idx_symbol_slack_bot_id 
ON symbol_slack_scores(bot_id);
