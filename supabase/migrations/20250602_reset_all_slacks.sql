-- Reset all slack scores to baseline for fresh start tomorrow
-- This sets all symbols to slack_score = 100, clears trade history from slack table

TRUNCATE TABLE symbol_slack_scores;

-- Verify reset
SELECT 
    COUNT(*) as total_symbols,
    AVG(slack_score) as avg_slack,
    MIN(slack_score) as min_slack,
    MAX(slack_score) as max_slack
FROM symbol_slack_scores;
