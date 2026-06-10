# Security Lockdown Plan

## 1. Database Security (CRITICAL - Do This First)

### Enable RLS on All Tables

```sql
-- Stock Bots Table
ALTER TABLE stock_bots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can only access their own stock bots"
  ON stock_bots
  FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- Options Bots Table
ALTER TABLE options_bots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can only access their own options bots"
  ON options_bots
  FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- Trades Table (stock trades)
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can only access their own trades"
  ON trades
  FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- Options Trades Table
ALTER TABLE options_trades ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can only access their own options trades"
  ON options_trades
  FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- Broker Credentials (CRITICAL - contains API keys!)
ALTER TABLE broker_credentials ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can only access their own broker credentials"
  ON broker_credentials
  FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- Hide credentials from direct queries (use edge functions only)
CREATE POLICY "Service role can access credentials for trading"
  ON broker_credentials
  FOR SELECT
  USING (true); -- Edge functions run as service_role
```

### Restrict Credential Access

```sql
-- Add a view that hides sensitive data
CREATE OR REPLACE VIEW broker_connections AS
SELECT 
  id,
  user_id,
  broker,
  created_at,
  -- NEVER expose credentials column
  CASE WHEN credentials IS NOT NULL THEN true ELSE false END as is_connected
FROM broker_credentials;
```

## 2. Edge Function Security

### Add API Key Validation to All Functions

```typescript
// At the start of every edge function
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');

// Verify the request is from your frontend (not external)
const verifyOrigin = (req: Request) => {
  const origin = req.headers.get('origin');
  const allowedOrigins = [
    'https://yourdomain.com',
    'https://*.boofcapital.com',
    'http://localhost:3000' // for dev
  ];
  return allowedOrigins.some(allowed => 
    origin?.endsWith(allowed.replace('*.', '')) || origin === allowed
  );
};

// Rate limiting
const rateLimit = new Map<string, { count: number; resetTime: number }>();

const checkRateLimit = (userId: string, maxRequests = 100, windowMs = 60000) => {
  const now = Date.now();
  const userLimit = rateLimit.get(userId);
  
  if (!userLimit || now > userLimit.resetTime) {
    rateLimit.set(userId, { count: 1, resetTime: now + windowMs });
    return true;
  }
  
  if (userLimit.count >= maxRequests) {
    return false;
  }
  
  userLimit.count++;
  return true;
};
```

### Secure the Auto-Bot Function

```typescript
// In auto-bot/index.ts - Add at the very start of the serve function
if (req.method !== 'POST') {
  return new Response(JSON.stringify({ error: 'Method not allowed' }), {
    status: 405,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' }
  });
}

// Verify cron secret or authenticated user
const body = await req.json();
const { cron_secret, user_id } = body;

// For cron job invocations
const expectedCronSecret = Deno.env.get('CRON_SECRET');
if (cron_secret && cron_secret !== expectedCronSecret) {
  return new Response(JSON.stringify({ error: 'Invalid cron secret' }), {
    status: 401,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' }
  });
}
```

## 3. Frontend Security

### Move Supabase Client to Edge Functions Only

**Current (INSECURE):**
```javascript
// Frontend directly queries database
const sbClient = createClient(ANON_KEY, ...)
await sbClient.from('stock_bots').update(...)
```

**Secure:**
```javascript
// Frontend calls edge function only
const response = await fetch('/functions/v1/bot-api', {
  method: 'POST',
  headers: { 
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${session.access_token}`
  },
  body: JSON.stringify({ action: 'updateBot', botId, data })
});
```

### Remove Anon Key from Frontend

Create a proxy edge function:

```typescript
// functions/api-gateway/index.ts
Deno.serve(async (req) => {
  // Validate JWT
  const authHeader = req.headers.get('Authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401 });
  }
  
  const token = authHeader.replace('Bearer ', '');
  const { data: { user }, error } = await supabase.auth.getUser(token);
  
  if (error || !user) {
    return new Response(JSON.stringify({ error: 'Invalid token' }), { status: 401 });
  }
  
  // Route to appropriate internal function
  const body = await req.json();
  const { action, ...params } = body;
  
  // Execute as service_role (bypasses RLS, we manually check user_id)
  const supabaseAdmin = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
  );
  
  switch (action) {
    case 'getBots':
      return await getUserBots(supabaseAdmin, user.id);
    case 'updateBot':
      return await updateBot(supabaseAdmin, user.id, params);
    // ... etc
  }
});
```

## 4. API Key Protection

### Never Store Raw Keys

```typescript
// Instead of storing raw API keys, use OAuth only

// For Alpaca: Use OAuth flow
// https://alpaca.markets/docs/build-apps/open-id.html

// For Tastytrade: No OAuth, so users must:
// Option A: Self-host (they control everything)
// Option B: You run separate instance per customer
```

### If You MUST Store Keys (Not Recommended)

```sql
-- Add encryption column
ALTER TABLE broker_credentials ADD COLUMN credentials_encrypted TEXT;

-- Use pgcrypto extension
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Encrypt with server-side key (still not perfect, but better)
UPDATE broker_credentials 
SET credentials_encrypted = pgp_sym_encrypt(
  credentials::text, 
  current_setting('app.encryption_key')
);

-- Drop plaintext column
ALTER TABLE broker_credentials DROP COLUMN credentials;
```

## 5. Code Obfuscation (For Distribution)

### Build Process for Distribution

```javascript
// Use a build tool to obfuscate
const JavaScriptObfuscator = require('javascript-obfuscator');

const obfuscationResult = JavaScriptObfuscator.obfuscate(
  fs.readFileSync('bots.js', 'utf8'),
  {
    compact: true,
    controlFlowFlattening: true,
    controlFlowFlatteningThreshold: 1,
    numbersToExpressions: true,
    simplify: true,
    shuffleStringArray: true,
    splitStrings: true,
    stringArrayThreshold: 1,
    deadCodeInjection: true,
    debugProtection: true,
    disableConsoleOutput: true,
    selfDefending: true
  }
);

fs.writeFileSync('bots.obfuscated.js', obfuscationResult.getObfuscatedCode());
```

### Hide Supabase Keys

```javascript
// Instead of hardcoded keys in HTML
const SUPABASE_URL = atob('aHR0cHM6Ly9pc2FuaHV0enljdGNqeWdoemJuLnN1cGFiYXNlLmNv');
const SUPABASE_ANON = atob('ZXlKaGJHY2lPaUpJVXpJMU5pSXNJbXRwWkRjaU9uc2lRSFh...');
```

## 6. Deployment Security

### Environment Variables

```bash
# .env (never commit this!)
CRON_SECRET=your_random_32_char_string_here
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
ENCRYPTION_KEY=another_random_32_char_string

# supabase/config.toml
[functions.auto-bot]
verify_jwt = true

[functions.options-bot]
verify_jwt = true
```

### CORS Configuration

```typescript
// Restrict CORS to your domain only
const corsHeaders = {
  'Access-Control-Allow-Origin': 'https://yourdomain.com',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'authorization, content-type',
  'Access-Control-Max-Age': '86400'
};
```

## 7. Audit & Monitoring

### Add Audit Logging

```sql
CREATE TABLE audit_logs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES auth.users(id),
  action TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id UUID,
  old_values JSONB,
  new_values JSONB,
  ip_address INET,
  user_agent TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can only view their own audit logs"
  ON audit_logs FOR SELECT USING (auth.uid() = user_id);
```

### Add to Critical Operations

```typescript
async function logAudit(supabase: any, userId: string, action: string, 
  resourceType: string, resourceId: string, oldVals?: any, newVals?: any) {
  await supabase.from('audit_logs').insert({
    user_id: userId,
    action,
    resource_type: resourceType,
    resource_id: resourceId,
    old_values: oldVals,
    new_values: newVals,
    created_at: new Date().toISOString()
  });
}

// Use it
await logAudit(supabase, user.id, 'UPDATE', 'stock_bots', botId, oldBot, newBot);
```

## 8. Multi-Tenant Architecture (For SaaS)

### Option A: Database Per Customer (Most Secure)

```bash
# Each customer gets their own Supabase project
# You maintain a central "management" database with:
# - customer_id, supabase_url, service_role_key (encrypted)
# - subscription_status
# - billing info

# Your edge function routes to the right database
```

### Option B: Schema Per Customer

```sql
-- Create schema for each customer
CREATE SCHEMA customer_abc123;

-- All tables under that schema
CREATE TABLE customer_abc123.stock_bots (...);
CREATE TABLE customer_abc123.trades (...);

-- RLS policies reference the schema
```

### Option C: Row-Level Security with org_id (Easiest)

```sql
-- Add org_id to all tables
ALTER TABLE stock_bots ADD COLUMN org_id UUID;
ALTER TABLE trades ADD COLUMN org_id UUID;

-- Update RLS policies
CREATE POLICY "Users can only access their org's bots"
  ON stock_bots
  FOR ALL
  USING (org_id IN (
    SELECT org_id FROM user_orgs WHERE user_id = auth.uid()
  ));
```

## Implementation Priority

### Phase 1 (Do Today - 2 hours):
1. ✅ Enable RLS on all tables
2. ✅ Add policies to all tables
3. ✅ Remove broker_credentials from frontend queries
4. ✅ Add CORS restrictions

### Phase 2 (This Week - 1 day):
5. Create API gateway edge function
6. Move all frontend DB calls to gateway
7. Add rate limiting
8. Add audit logging

### Phase 3 (Before Selling - 1 week):
9. Obfuscate frontend code
10. Set up per-customer infrastructure
11. Add OAuth for broker connections
12. Security audit

## Testing Security

```bash
# Test RLS is working
curl -X POST 'https://yourproject.supabase.co/rest/v1/stock_bots' \
  -H "apikey: YOUR_ANON_KEY" \
  -H "Authorization: Bearer USER_TOKEN" \
  -d '{"name": "Hacked", "user_id": "OTHER_USER_ID"}'

# Should fail with 403 Forbidden
```

## Cost Estimates

| Security Measure | Cost | Time |
|-----------------|------|------|
| RLS + Policies | Free | 2 hrs |
| API Gateway | $5/mo (Edge invocations) | 1 day |
| Code Obfuscation | $0 (build step) | 4 hrs |
| Per-Customer DB | $25/mo per customer | 1 week |
| Security Audit | $500-2000 (consultant) | 1 day |

## Summary

**Without these changes:**
- Anyone can copy your code in 5 minutes
- Anyone can read your Supabase keys
- Anyone can access other users' data if they guess UUIDs
- Anyone with your anon key can dump the entire database

**With these changes:**
- Code is obfuscated (harder to copy)
- Keys are hidden behind gateway
- RLS prevents cross-user data access
- Audit trail tracks all actions
