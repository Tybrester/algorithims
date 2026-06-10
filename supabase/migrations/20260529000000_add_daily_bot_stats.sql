-- Daily bot stats for historical analysis
CREATE TABLE IF NOT EXISTS daily_bot_stats (
  id BIGSERIAL PRIMARY KEY,
  bot_id UUID NOT NULL REFERENCES options_bots(id) ON DELETE CASCADE,
  bot_name TEXT NOT NULL,
  bot_symbol TEXT NOT NULL,
  bot_signal TEXT NOT NULL,
  date DATE NOT NULL,
  
  -- Trade counts
  total_trades INTEGER DEFAULT 0,
  winning_trades INTEGER DEFAULT 0,
  losing_trades INTEGER DEFAULT 0,
  
  -- P&L metrics
  total_pnl NUMERIC DEFAULT 0,
  total_premium NUMERIC DEFAULT 0,
  avg_win NUMERIC DEFAULT 0,
  avg_loss NUMERIC DEFAULT 0,
  profit_factor NUMERIC DEFAULT 0,
  win_rate NUMERIC DEFAULT 0,
  
  -- Trade timing
  first_trade_time TIMESTAMPTZ,
  last_trade_time TIMESTAMPTZ,
  
  -- Cooldown tracking
  consecutive_losses INTEGER DEFAULT 0,
  max_consecutive_losses INTEGER DEFAULT 0,
  cooldown_triggered BOOLEAN DEFAULT false,
  cooldown_minutes INTEGER DEFAULT 0,
  
  -- Daily limits
  daily_profit_target NUMERIC DEFAULT 0,
  daily_floor_amount NUMERIC DEFAULT 0,
  hit_profit_target BOOLEAN DEFAULT false,
  hit_daily_floor BOOLEAN DEFAULT false,
  
  -- Paper trading specific
  paper_balance_start NUMERIC DEFAULT 0,
  paper_balance_end NUMERIC DEFAULT 0,
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  UNIQUE(bot_id, date)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_daily_bot_stats_bot_id ON daily_bot_stats(bot_id);
CREATE INDEX IF NOT EXISTS idx_daily_bot_stats_date ON daily_bot_stats(date);
CREATE INDEX IF NOT EXISTS idx_daily_bot_stats_bot_date ON daily_bot_stats(bot_id, date);

-- Add comments
COMMENT ON TABLE daily_bot_stats IS 'Daily performance metrics for each bot, aggregated from options_trades';
COMMENT ON COLUMN daily_bot_stats.profit_factor IS 'Total winning P&L / Total losing P&L (absolute value)';
COMMENT ON COLUMN daily_bot_stats.win_rate IS 'Winning trades / Total trades as percentage';
