-- Add slack trend tracking columns to options_bots table
ALTER TABLE options_bots 
ADD COLUMN IF NOT EXISTS slack_trend NUMERIC DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS regime_status TEXT DEFAULT 'NORMAL' CHECK (regime_status IN ('NORMAL', 'CAUTION', 'DEGRADED')),
ADD COLUMN IF NOT EXISTS slack_history JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN options_bots.slack_trend IS 'Rolling average of last 10 slack values (ATR units)';
COMMENT ON COLUMN options_bots.regime_status IS 'Signal quality status: NORMAL (≥0.8), CAUTION (0.6-0.8), DEGRADED (<0.6)';
COMMENT ON COLUMN options_bots.slack_history IS 'Last 10 slack values for rolling average calculation';
