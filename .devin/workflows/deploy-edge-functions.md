---
description: Deploy Supabase Edge Functions
tags: [deployment, supabase, edge-functions]
---

# Deploy Supabase Edge Functions

Quick workflow to deploy updated edge functions without copy/pasting code.

## Prerequisites
- Supabase CLI installed: `npm install -g supabase`
- Logged in: `npx supabase login`

## Deploy All Functions

```bash
// turbo
npx supabase functions deploy auto-bot --project-ref isanhutzyctcjygjhzbn
npx supabase functions deploy options-bot --project-ref isanhutzyctcjygjhzbn
```

## Deploy Single Function

```bash
# Auto-bot only
npx supabase functions deploy auto-bot --project-ref isanhutzyctcjygjhzbn

# Options-bot only  
npx supabase functions deploy options-bot --project-ref isanhutzyctcjygjhzbn
```

## Alternative: Deploy via Dashboard

1. Go to: https://supabase.com/dashboard/project/isanhutzyctcjygjhzbn/functions
2. Click the function name (auto-bot or options-bot)
3. Click "Deploy"

## Verify Deployment

Check logs in Supabase Dashboard → Edge Functions → [function name] → Logs

## Troubleshooting

- If deploy fails, check for TypeScript errors in the code
- Ensure `SUPABASE_ACCESS_TOKEN` is set if using CLI
- Dashboard deployment is more reliable for quick updates
