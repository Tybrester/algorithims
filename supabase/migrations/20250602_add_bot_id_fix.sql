-- Add bot_id column first
ALTER TABLE symbol_slack_scores ADD COLUMN IF NOT EXISTS bot_id uuid REFERENCES options_bots(id) ON DELETE CASCADE;

-- Now backfill from options_trades
INSERT INTO symbol_slack_scores (symbol, user_id, bot_id, bot_signal, total_trades, winning_trades, total_pnl, avg_pnl_per_trade, win_rate, slack_score, last_trade_at)
SELECT 
    t.symbol,
    t.user_id,
    t.bot_id,
    COALESCE(t.signal_version, 'boof23') as bot_signal,
    COUNT(*) as total_trades,
    SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
    SUM(t.pnl) as total_pnl,
    SUM(t.pnl) / NULLIF(COUNT(*), 0) as avg_pnl_per_trade,
    (SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END)::decimal / NULLIF(COUNT(*), 0)) * 100 as win_rate,
    100 + (SUM(t.pnl) / 100) as slack_score,
    MAX(t.closed_at) as last_trade_at
FROM options_trades t
WHERE t.status = 'closed' 
  AND t.pnl IS NOT NULL
GROUP BY t.symbol, t.user_id, t.bot_id, COALESCE(t.signal_version, 'boof23')
ON CONFLICT (symbol, user_id, bot_id) 
DO UPDATE SET
    bot_signal = EXCLUDED.bot_signal,
    total_trades = EXCLUDED.total_trades,
    winning_trades = EXCLUDED.winning_trades,
    total_pnl = EXCLUDED.total_pnl,
    avg_pnl_per_trade = EXCLUDED.avg_pnl_per_trade,
    win_rate = EXCLUDED.win_rate,
    slack_score = EXCLUDED.slack_score,
    last_trade_at = EXCLUDED.last_trade_at,
    updated_at = now();
