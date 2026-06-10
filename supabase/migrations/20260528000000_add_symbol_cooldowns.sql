-- Per-symbol cooldown tracking: after 2 SL hits on same symbol, pause that symbol for 5 min
ALTER TABLE options_bots ADD COLUMN IF NOT EXISTS symbol_cooldowns JSONB DEFAULT '{}'::jsonb;
COMMENT ON COLUMN options_bots.symbol_cooldowns IS 'Map of symbol -> {losses: N, until: ISO timestamp} for per-symbol cooldown tracking';
