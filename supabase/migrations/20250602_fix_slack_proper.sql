-- Fix slack scores to work like this morning but per-bot
-- Use proper formula with bounds (50-300) like the original

-- First, recalculate all slack scores with proper formula and clamping
UPDATE symbol_slack_scores
SET slack_score = GREATEST(50, LEAST(300,
    CASE 
        WHEN total_trades = 0 THEN 100
        WHEN avg_pnl_per_trade IS NULL OR avg_pnl_per_trade = 0 THEN 100
        ELSE 
            -- Formula: win_rate * avg_pnl * ln(total_trades + 1)
            -- But cap negative P&L impact so scores don't go below 50
            GREATEST(-50, win_rate * 
                CASE 
                    WHEN avg_pnl_per_trade < -10 THEN -10  -- Cap negative P&L impact
                    ELSE avg_pnl_per_trade 
                END * 
                ln(total_trades + 1)
            ) + 100  -- Shift so baseline is 100
    END
)),
updated_at = now();

-- Verify the distribution looks right
SELECT 
    CASE 
        WHEN slack_score >= 200 THEN 'Excellent (200+)'
        WHEN slack_score >= 150 THEN 'Very Good (150-199)'
        WHEN slack_score >= 100 THEN 'Good (100-149)'
        WHEN slack_score >= 70 THEN 'Okay (70-99)'
        ELSE 'Poor (<70)'
    END as tier,
    COUNT(*) as count,
    ROUND(AVG(slack_score), 1) as avg_score,
    MIN(slack_score) as min_score,
    MAX(slack_score) as max_score
FROM symbol_slack_scores
GROUP BY 1
ORDER BY AVG(slack_score) DESC;
