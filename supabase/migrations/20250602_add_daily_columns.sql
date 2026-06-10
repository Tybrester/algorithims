-- Add daily_pnl and daily_trades columns for TODAY P&L display

ALTER TABLE symbol_slack_scores 
ADD COLUMN IF NOT EXISTS daily_pnl decimal(12,2) DEFAULT 0,
ADD COLUMN IF NOT EXISTS daily_trades int DEFAULT 0;

-- Backfill daily P&L from today's closed trades
UPDATE symbol_slack_scores s
SET daily_pnl = COALESCE(today.today_pnl, 0),
    daily_trades = COALESCE(today.today_trades, 0)
FROM (
    SELECT 
        bot_id,
        symbol,
        SUM(pnl) as today_pnl,
        COUNT(*) as today_trades
    FROM options_trades
    WHERE status = 'closed'
      AND pnl IS NOT NULL
      AND DATE(closed_at) = CURRENT_DATE
    GROUP BY bot_id, symbol
) today
WHERE s.bot_id = today.bot_id 
  AND s.symbol = today.symbol;
