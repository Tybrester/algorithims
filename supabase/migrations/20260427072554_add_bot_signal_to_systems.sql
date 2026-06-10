alter table options_bots add column if not exists bot_signal text default 'supertrend';
alter table options_bots add column if not exists bot_expiry_type text default 'weekly';
alter table options_bots add column if not exists bot_scan_mode text default 'single';
