-- Check what columns exist and add missing ones

-- First, show existing columns
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'symbol_slack_scores';

-- Add columns one by one with IF NOT EXISTS
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'symbol_slack_scores' AND column_name = 'bot_id') THEN
        ALTER TABLE symbol_slack_scores ADD COLUMN bot_id uuid REFERENCES options_bots(id) ON DELETE CASCADE;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'symbol_slack_scores' AND column_name = 'losing_trades') THEN
        ALTER TABLE symbol_slack_scores ADD COLUMN losing_trades int DEFAULT 0;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'symbol_slack_scores' AND column_name = 'daily_pnl') THEN
        ALTER TABLE symbol_slack_scores ADD COLUMN daily_pnl decimal(12,2) DEFAULT 0;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'symbol_slack_scores' AND column_name = 'daily_trades') THEN
        ALTER TABLE symbol_slack_scores ADD COLUMN daily_trades int DEFAULT 0;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'symbol_slack_scores' AND column_name = 'created_at') THEN
        ALTER TABLE symbol_slack_scores ADD COLUMN created_at timestamp with time zone DEFAULT now();
    END IF;
END $$;
