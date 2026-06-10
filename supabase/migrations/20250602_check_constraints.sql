-- Check the table structure and constraints
SELECT 
    column_name, 
    data_type, 
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_name = 'symbol_slack_scores' 
ORDER BY ordinal_position;

-- Check constraints
SELECT conname, pg_get_constraintdef(oid) 
FROM pg_constraint 
WHERE conrelid = 'symbol_slack_scores'::regclass;

-- Check unique indexes
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'symbol_slack_scores';
