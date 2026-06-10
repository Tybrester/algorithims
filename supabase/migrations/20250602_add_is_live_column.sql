-- Add is_live column to options_bots if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'options_bots' 
                   AND column_name = 'is_live') THEN
        ALTER TABLE options_bots ADD COLUMN is_live BOOLEAN DEFAULT false;
    END IF;
END $$;

-- Add is_live column to stock_bots if it doesn't exist  
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'stock_bots' 
                   AND column_name = 'is_live') THEN
        ALTER TABLE stock_bots ADD COLUMN is_live BOOLEAN DEFAULT false;
    END IF;
END $$;

-- Refresh schema cache
NOTIFY pgrst, 'reload schema';
