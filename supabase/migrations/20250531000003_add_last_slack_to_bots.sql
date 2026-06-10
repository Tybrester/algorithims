-- Add last_slack column to options_bots for UI display
ALTER TABLE options_bots 
ADD COLUMN IF NOT EXISTS last_slack NUMERIC DEFAULT NULL;

COMMENT ON COLUMN options_bots.last_slack IS 'Last signal slack value for UI display (Boof 22/23)';
