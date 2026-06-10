-- Diagnostic: Check slack scores and trades data

-- Check if slack scores exist and their bot_id values
SELECT 'symbol_slack_scores count' as check_type, 
       COUNT(*) as total_rows,
       COUNT(bot_id) as with_bot_id,
       COUNT(*) - COUNT(bot_id) as null_bot_id
FROM symbol_slack_scores
WHERE user_id = auth.uid();

-- Check trades with bot_id
SELECT 'options_trades with bot_id' as check_type,
       COUNT(*) as total_closed_trades,
       COUNT(bot_id) as with_bot_id,
       COUNT(DISTINCT bot_id) as unique_bots
FROM options_trades
WHERE status = 'closed' 
  AND pnl IS NOT NULL
  AND user_id = auth.uid();

-- Check sample of recent trades
SELECT 'recent trades sample' as check_type,
       id, symbol, bot_id, signal_version, pnl, closed_at
FROM options_trades
WHERE status = 'closed' 
  AND pnl IS NOT NULL
  AND user_id = auth.uid()
ORDER BY closed_at DESC
LIMIT 5;

-- Check if any slack scores exist for this user
SELECT 'slack scores sample' as check_type,
       symbol, bot_id, bot_signal, total_trades, total_pnl, slack_score
FROM symbol_slack_scores
WHERE user_id = auth.uid()
LIMIT 5;
