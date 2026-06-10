-- Run this in Supabase SQL Editor

create table if not exists public.webhook_secrets (
  user_id uuid references auth.users primary key,
  secret text not null,
  created_at timestamptz default now()
);

alter table public.webhook_secrets enable row level security;

create policy "Users read own secret" on public.webhook_secrets
  for select using (auth.uid() = user_id);

-- Auto-generate a secret when a user first needs one
create or replace function public.get_or_create_webhook_secret(p_user_id uuid)
returns text language plpgsql security definer as $$
declare
  v_secret text;
begin
  select secret into v_secret from public.webhook_secrets where user_id = p_user_id;
  if v_secret is null then
    v_secret := encode(gen_random_bytes(24), 'hex');
    insert into public.webhook_secrets (user_id, secret) values (p_user_id, v_secret);
  end if;
  return v_secret;
end;
$$;
