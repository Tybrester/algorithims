-- Rebuild all slack scores using correct formula
-- Formula: 100 + (win_rate - 50)*1.5 + avg_pnl/20 + ln(total_trades+1)*3, clamped 50-300

DELETE FROM symbol_slack_scores;

INSERT INTO symbol_slack_scores (
    symbol, user_id, bot_id, bot_signal, 
    total_trades, winning_trades, total_pnl, avg_pnl_per_trade, win_rate,
    slack_score, last_trade_at, daily_pnl, daily_trades, updated_at
)
SELECT 
    t.symbol,
    t.user_id,
    t.bot_id,
    COALESCE(t.signal_version, 'boof23') as bot_signal,
    COUNT(*) as total_trades,
    SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
    SUM(t.pnl) as total_pnl,
    SUM(t.pnl) / COUNT(*) as avg_pnl_per_trade,
    (SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END)::decimal / COUNT(*)) * 100 as win_rate,
    -- Slack score formula with baseline 100
    GREATEST(50, LEAST(300,
        100 
        + (((SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END)::decimal / COUNT(*)) * 100 - 50) * 1.5)
        + ((SUM(t.pnl) / COUNT(*)) / 20)
        + LN(COUNT(*) + 1) * 3
    )) as slack_score,
    MAX(t.closed_at) as last_trade_at,
    SUM(CASE WHEN DATE(t.closed_at) = CURRENT_DATE THEN t.pnl ELSE 0 END) as daily_pnl,
    SUM(CASE WHEN DATE(t.closed_at) = CURRENT_DATE THEN 1 ELSE 0 END) as daily_trades,
    now() as updated_at
FROM options_trades t
WHERE t.status = 'closed' 
  AND t.pnl IS NOT NULL
  AND t.bot_id IS NOT NULL
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
    daily_pnl = EXCLUDED.daily_pnl,
    daily_trades = EXCLUDED.daily_trades,
    updated_at = now();
