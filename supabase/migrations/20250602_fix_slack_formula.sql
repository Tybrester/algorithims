-- Fix slack scores to use proper formula: win_rate * avg_pnl * ln(total_trades + 1)
-- This creates meaningful differentiation between symbols

UPDATE symbol_slack_scores
SET slack_score = GREATEST(50, LEAST(300,
    (win_rate * avg_pnl_per_trade * ln(total_trades + 1))
)),
updated_at = now()
WHERE total_trades > 0;

-- For symbols with no trades, reset to baseline 100
UPDATE symbol_slack_scores
SET slack_score = 100,
updated_at = now()
WHERE total_trades = 0 OR total_trades IS NULL;

-- Verify the distribution
SELECT 
    CASE 
        WHEN slack_score >= 150 THEN 'Excellent (150+)'
        WHEN slack_score >= 100 THEN 'Good (100-149)'
        WHEN slack_score >= 50 THEN 'Okay (50-99)'
        ELSE 'Poor (<50)'
    END as tier,
    COUNT(*) as count,
    ROUND(AVG(slack_score), 1) as avg_score
FROM symbol_slack_scores
GROUP BY 1
ORDER BY AVG(slack_score) DESC;
