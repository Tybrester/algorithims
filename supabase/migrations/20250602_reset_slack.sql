-- Reset to exact trigger formula - no clamping, no rounding
-- Use what worked this morning but per-bot

UPDATE symbol_slack_scores
SET slack_score = 
    CASE 
        WHEN total_trades = 0 THEN 100
        ELSE (win_rate * avg_pnl_per_trade * ln(total_trades + 1))
    END,
    updated_at = now();

-- Show actual distribution
SELECT 
    ROUND(slack_score, 0) as score,
    COUNT(*) as count
FROM symbol_slack_scores
WHERE total_trades > 0
GROUP BY ROUND(slack_score, 0)
ORDER BY score DESC
LIMIT 30;
