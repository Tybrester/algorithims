-- Fix: Backfill slack scores from ALL closed trades (not just current user)
-- Run this as service_role or admin

-- First, let's see what we have
SELECT 'Current slack scores' as info, COUNT(*) as count, 
       COUNT(CASE WHEN total_trades > 0 THEN 1 END) as with_trades
FROM symbol_slack_scores;

-- Backfill from options_trades for ALL users
INSERT INTO symbol_slack_scores (symbol, user_id, bot_id, bot_signal, total_trades, winning_trades, total_pnl, avg_pnl_per_trade, win_rate, slack_score, last_trade_at)
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
    ((SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END)::decimal / COUNT(*)) * 100) * 
     (SUM(t.pnl) / COUNT(*)) * 
     ln(COUNT(*) + 1) as slack_score,
    MAX(t.closed_at) as last_trade_at
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
    updated_at = now();

-- Also handle legacy: trades with NULL bot_id - aggregate by bot_signal only
-- First delete orphaned legacy rows
DELETE FROM symbol_slack_scores WHERE bot_id IS NULL;

-- Then insert aggregated by signal
INSERT INTO symbol_slack_scores (symbol, user_id, bot_id, bot_signal, total_trades, winning_trades, total_pnl, avg_pnl_per_trade, win_rate, slack_score, last_trade_at)
SELECT 
    t.symbol,
    t.user_id,
    NULL as bot_id,  -- Legacy: no bot_id
    COALESCE(t.signal_version, 'boof23') as bot_signal,
    COUNT(*) as total_trades,
    SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
    SUM(t.pnl) as total_pnl,
    SUM(t.pnl) / COUNT(*) as avg_pnl_per_trade,
    (SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END)::decimal / COUNT(*)) * 100 as win_rate,
    ((SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END)::decimal / COUNT(*)) * 100) * 
     (SUM(t.pnl) / COUNT(*)) * 
     ln(COUNT(*) + 1) as slack_score,
    MAX(t.closed_at) as last_trade_at
FROM options_trades t
WHERE t.status = 'closed' 
  AND t.pnl IS NOT NULL
  AND t.bot_id IS NULL  -- Only trades without bot_id
GROUP BY t.symbol, t.user_id, COALESCE(t.signal_version, 'boof23')
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

-- Verify results
SELECT 'After fix' as info, 
       COUNT(*) as total_rows,
       COUNT(CASE WHEN total_trades > 0 THEN 1 END) as with_trades,
       SUM(total_trades) as total_trades_sum
FROM symbol_slack_scores;
