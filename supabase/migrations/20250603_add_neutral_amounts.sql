ALTER TABLE options_bots
ADD COLUMN IF NOT EXISTS neutral_trend_amount NUMERIC,
ADD COLUMN IF NOT EXISTS neutral_chop_amount NUMERIC;
