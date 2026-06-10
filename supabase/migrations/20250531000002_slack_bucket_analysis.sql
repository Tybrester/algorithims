-- Slack bucket analysis query
-- Run this after collecting ~200 trades with entry_slack values

SELECT 
  CASE 
    WHEN entry_slack < 0.3 THEN '0.0-0.3'
    WHEN entry_slack < 0.6 THEN '0.3-0.6'
    WHEN entry_slack < 0.9 THEN '0.6-0.9'
    WHEN entry_slack < 1.2 THEN '0.9-1.2'
    ELSE '1.2+'
  END as slack_bucket,
  COUNT(*) as trades,
  AVG(pnl) as avg_pnl,
  SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) as win_rate,
  AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
  AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss,
  SUM(pnl) as total_pnl
FROM options_trades
WHERE status = 'closed' 
  AND bot_signal = 'boof23'
  AND entry_slack IS NOT NULL
GROUP BY 
  CASE 
    WHEN entry_slack < 0.3 THEN '0.0-0.3'
    WHEN entry_slack < 0.6 THEN '0.3-0.6'
    WHEN entry_slack < 0.9 THEN '0.6-0.9'
    WHEN entry_slack < 1.2 THEN '0.9-1.2'
    ELSE '1.2+'
  END
ORDER BY 
  CASE 
    WHEN entry_slack < 0.3 THEN 1
    WHEN entry_slack < 0.6 THEN 2
    WHEN entry_slack < 0.9 THEN 3
    WHEN entry_slack < 1.2 THEN 4
    ELSE 5
  END;
