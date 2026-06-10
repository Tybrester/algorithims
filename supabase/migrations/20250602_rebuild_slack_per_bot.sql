-- Rebuild slack scores properly from scratch - per bot, sane formula
-- This creates the system like this morning but per-bot

-- Step 1: Truncate and rebuild with correct baseline
TRUNCATE symbol_slack_scores;

-- Step 2: Insert per-bot symbol stats with PROPER formula
-- Formula: 100 + (win_rate - 50) * 2 + (avg_pnl / 10) + ln(trades + 1) * 5
-- This gives ~100 baseline, +/- 50 for win/loss, +/- for P&L, small trade bonus
INSERT INTO symbol_slack_scores (
    symbol, bot_id, bot_signal, 
    total_trades, winning_trades, losing_trades, win_rate,
    total_pnl, avg_pnl_per_trade, daily_pnl, daily_trades,
    slack_score, created_at, updated_at, user_id
)
SELECT 
    t.symbol,
    b.id as bot_id,
    COALESCE(b.bot_signal, 'boof23') as bot_signal,
    COUNT(*) as total_trades,
    COUNT(*) FILTER (WHERE t.pnl > 0) as winning_trades,
    COUNT(*) FILTER (WHERE t.pnl <= 0) as losing_trades,
    (COUNT(*) FILTER (WHERE t.pnl > 0)::numeric / NULLIF(COUNT(*), 0) * 100) as win_rate,
    COALESCE(SUM(t.pnl), 0) as total_pnl,
    COALESCE(AVG(t.pnl), 0) as avg_pnl_per_trade,
    COALESCE(SUM(t.pnl) FILTER (WHERE DATE(t.filled_at) = CURRENT_DATE), 0) as daily_pnl,
    COUNT(*) FILTER (WHERE DATE(t.filled_at) = CURRENT_DATE) as daily_trades,
    -- SANE FORMULA: 100 baseline, +/- win rate deviation, +/- P&L factor, trade bonus
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
WHERE b.user_id IS NOT NULL
  AND t.status = 'closed'
  AND t.pnl IS NOT NULL
GROUP BY b.id, b.user_id, t.symbol, b.bot_signal;

-- Step 3: Add baseline 100 for symbols with no trades yet (per bot)
INSERT INTO symbol_slack_scores (
    symbol, bot_id, bot_signal,
    total_trades, winning_trades, losing_trades, win_rate,
    total_pnl, avg_pnl_per_trade, daily_pnl, daily_trades,
    slack_score, created_at, updated_at, user_id
)
SELECT DISTINCT
    s.symbol,
    b.id as bot_id,
    COALESCE(b.bot_signal, 'boof23') as bot_signal,
    0, 0, 0, 0, 0, 0, 0, 0, 100, NOW(), NOW(), b.user_id
FROM options_bots b
CROSS JOIN (SELECT DISTINCT symbol FROM options_trades WHERE user_id IS NOT NULL) s
WHERE b.user_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM symbol_slack_scores x 
    WHERE x.symbol = s.symbol AND x.bot_id = b.id
  );

-- Verify results
SELECT 
    CASE 
        WHEN slack_score >= 150 THEN 'Excellent'
        WHEN slack_score >= 100 THEN 'Good'
        WHEN slack_score >= 50 THEN 'Okay'
        ELSE 'Poor'
    END as tier,
    COUNT(*) as count,
    ROUND(AVG(slack_score), 1) as avg
FROM symbol_slack_scores
GROUP BY 1
ORDER BY 2 DESC;
