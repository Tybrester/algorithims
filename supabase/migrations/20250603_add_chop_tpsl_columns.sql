-- Add chop TP/SL columns to options_bots table
ALTER TABLE options_bots
ADD COLUMN IF NOT EXISTS chop_take_profit_pct NUMERIC DEFAULT 8,
ADD COLUMN IF NOT EXISTS chop_stop_loss_pct NUMERIC DEFAULT -6;
