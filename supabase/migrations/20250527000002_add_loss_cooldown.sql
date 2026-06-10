-- Add cooldown columns for loss streak protection
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS cooldown_until TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS consecutive_losses INTEGER DEFAULT 0;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS max_consecutive_losses INTEGER DEFAULT 7;
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS cooldown_minutes INTEGER DEFAULT 8;

-- Add comment explaining the columns
COMMENT ON COLUMN options_bots.cooldown_until IS 'Timestamp when bot can trade again after loss streak cooldown';
COMMENT ON COLUMN options_bots.consecutive_losses IS 'Current count of consecutive losing trades';
COMMENT ON COLUMN options_bots.max_consecutive_losses IS 'Number of consecutive losses before cooldown triggers (default: 7)';
COMMENT ON COLUMN options_bots.cooldown_minutes IS 'Minutes to pause trading after hitting max_consecutive_losses (default: 8)';
