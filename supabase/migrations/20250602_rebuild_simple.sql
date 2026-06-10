-- Simple rebuild without losing_trades column

TRUNCATE symbol_slack_scores;

INSERT INTO symbol_slack_scores (
    symbol, bot_id, bot_signal, 
    total_trades, winning_trades, win_rate,
    total_pnl, avg_pnl_per_trade, daily_pnl, daily_trades,
    slack_score, created_at, updated_at, user_id
)
SELECT 
    t.symbol,
    b.id as bot_id,
    COALESCE(b.bot_signal, 'boof23') as bot_signal,
    COUNT(*) as total_trades,
    COUNT(*) FILTER (WHERE t.pnl > 0) as winning_trades,
    (COUNT(*) FILTER (WHERE t.pnl > 0)::numeric / NULLIF(COUNT(*), 0) * 100) as win_rate,
    COALESCE(SUM(t.pnl), 0) as total_pnl,
    COALESCE(AVG(t.pnl), 0) as avg_pnl_per_trade,
    COALESCE(SUM(t.pnl) FILTER (WHERE DATE(t.closed_at) = CURRENT_DATE), 0) as daily_pnl,
    COUNT(*) FILTER (WHERE DATE(t.closed_at) = CURRENT_DATE) as daily_trades,
    -- Formula like this morning: 100 baseline, +/- win rate, +/- P&L
    GREATEST(50, LEAST(300,
        100 
        + ((COUNT(*) FILTER (WHERE t.pnl > 0)::numeric / NULLIF(COUNT(*), 0) * 100) - 50) * 1.5
        + (COALESCE(AVG(t.pnl), 0) / 20)
        + LN(COUNT(*) + 1) * 3
    )) as slack_score,
    NOW() as created_at,
    NOW() as updated_at,
    b.user_id
FROM options_bots b
JOIN options_trades t ON t.bot_id = b.id
WHERE t.status = 'closed' AND t.pnl IS NOT NULL
GROUP BY b.id, b.user_id, t.symbol, b.bot_signal;

-- Add baseline 100 for symbols with no trades (per bot)
INSERT INTO symbol_slack_scores (
    symbol, bot_id, bot_signal,
    total_trades, winning_trades, win_rate,
    total_pnl, avg_pnl_per_trade, daily_pnl, daily_trades,
    slack_score, created_at, updated_at, user_id
)
SELECT DISTINCT
    s.symbol,
    b.id as bot_id,
    COALESCE(b.bot_signal, 'boof23') as bot_signal,
    0, 0, 0, 0, 0, 0, 0, 100, NOW(), NOW(), b.user_id
FROM options_bots b
CROSS JOIN (SELECT DISTINCT symbol FROM options_trades) s
WHERE NOT EXISTS (
    SELECT 1 FROM symbol_slack_scores x 
    WHERE x.symbol = s.symbol AND x.bot_id = b.id
);
