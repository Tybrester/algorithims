-- Add exit_reason column if not exists
alter table options_trades add column if not exists exit_reason text;

-- Enable pg_cron extension (if not enabled)
create extension if not exists pg_cron;

-- Delete existing job if exists (direct SQL, ignores if not found)
delete from cron.job where jobname = 'tpsl-daemon';

-- Create cron job to call TP/SL daemon every 1 minute
select cron.schedule(
  'tpsl-daemon',      -- job name
  '*/1 * * * *',      -- every 1 minute
  $$
  select net.http_post(
    url:='https://isanhutzyctcjygjhzbn.supabase.co/functions/v1/options-bot',
    headers:='{"Content-Type": "application/json", "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDMzMDY4NjAsImV4cCI6MjA1ODg4Mjg2MH0._QCJQz5ZvHD2GjFYMGbI1WhfE0dDQRA_eQyzh1nD4pI"}'::jsonb,
    body:='{"action": "tpsl_daemon"}'::jsonb
  );
  $$
);

-- Verify job was created
select jobname, schedule, command from cron.job where jobname = 'tpsl-daemon';
