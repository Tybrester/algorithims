import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

// Rate limiter: 5 attempts per IP per 15 minutes
const rateLimitMap = new Map<string, { count: number; resetAt: number }>();
function checkRateLimit(ip: string): boolean {
  const now = Date.now();
  const window = 15 * 60 * 1000;
  const entry = rateLimitMap.get(ip);
  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(ip, { count: 1, resetAt: now + window });
    return true;
  }
  if (entry.count >= 5) return false;
  entry.count++;
  return true;
}

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

// Tastytrade Personal Grant flow - use refresh token to get access tokens
// LIVE API - your credentials are for production
const TASTY_LIVE_URL = 'https://api.tastytrade.com/oauth/token';
const TASTY_SANDBOX_URL = 'https://api.cert.tastytrade.com/oauth/token';

function extractClientIdFromJWT(token: string): string | null {
  try {
    const payload = token.split('.')[1];
    const decoded = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
    return decoded.aud || null;
  } catch { return null; }
}

async function tryRefreshToken(url: string, refreshToken: string, clientSecret: string): Promise<{ access_token: string; expires_in: number } | null> {
  const apiType = url.includes('cert') ? 'SANDBOX' : 'LIVE';
  
  // Extract client_id from JWT aud claim
  const clientId = extractClientIdFromJWT(refreshToken) || clientSecret;
  console.log(`[TastyOAuth] Trying ${apiType} API: client_id=${clientId}, client_secret_length=${clientSecret?.length}`);
  
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
        client_id: clientId,
        client_secret: clientSecret
      })
    });
    
    console.log(`[TastyOAuth] ${apiType} fetch completed, status=${res.status}`);
    
    let responseText = '';
    try {
      responseText = await res.text();
      console.log(`[TastyOAuth] ${apiType} raw response: ${responseText || '(empty)'}`);
    } catch (textErr) {
      console.error(`[TastyOAuth] ${apiType} failed to read response text:`, textErr);
    }
    
    if (res.status === 200 && responseText) {
      try {
        const json = JSON.parse(responseText);
        console.log(`[TastyOAuth] ${apiType} parsed JSON: has_access_token=${!!json.access_token}, error=${json.error || 'none'}`);
        if (json.access_token) {
          console.log(`[TastyOAuth] SUCCESS with ${apiType} API!`);
          return { access_token: json.access_token, expires_in: json.expires_in || 900 };
        }
      } catch (parseErr) {
        console.error(`[TastyOAuth] ${apiType} JSON parse error:`, parseErr);
      }
    } else {
      console.log(`[TastyOAuth] ${apiType} returned status ${res.status}, no valid token`);
    }
    return null;
  } catch (err) {
    console.error(`[TastyOAuth] ${apiType} CRASHED:`, err);
    return null;
  }
}

async function getAccessToken(refreshToken: string, clientSecret: string): Promise<{ access_token: string; expires_in: number } | null> {
  console.log(`[TastyOAuth] Refreshing token via LIVE API: refresh_token_length=${refreshToken?.length}, client_secret_length=${clientSecret?.length}`);
  
  // LIVE API only
  const liveResult = await tryRefreshToken(TASTY_LIVE_URL, refreshToken, clientSecret);
  if (liveResult) return liveResult;
  
  console.error('[TastyOAuth] LIVE API failed');
  return null;
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });

  const ip = req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown';
  if (!checkRateLimit(ip)) {
    return new Response(JSON.stringify({ error: 'Too many attempts. Try again in 15 minutes.' }), {
      status: 429, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }

  const url = new URL(req.url);
  const action = url.searchParams.get('action');

  // Personal Grant flow: user provides refresh token directly
  if (action === 'connect') {
    const cl = Number(req.headers.get('content-length') || 0);
    if (cl > 8192) return new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    const raw = await req.text();
    if (raw.length > 8192) return new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    let parsedConnect: any;
    try { parsedConnect = JSON.parse(raw); } catch { return new Response(JSON.stringify({ error: 'Invalid JSON' }), { status: 422, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }); }
    const user_id       = typeof parsedConnect.user_id === 'string' ? parsedConnect.user_id.trim().slice(0, 64) : '';
    const refresh_token = typeof parsedConnect.refresh_token === 'string' ? parsedConnect.refresh_token.trim().slice(0, 2048) : '';
    const client_secret = typeof parsedConnect.client_secret === 'string' ? parsedConnect.client_secret.trim().slice(0, 512) : '';
    if (!user_id || !refresh_token || !client_secret) {
      return new Response(JSON.stringify({ error: 'user_id, refresh_token, and client_secret required' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
    if (!/^[0-9a-f-]{36}$/i.test(user_id)) return new Response(JSON.stringify({ error: 'Invalid user_id' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    try {
      // Try to get initial access token (non-blocking — save creds regardless)
      const token = await getAccessToken(refresh_token, client_secret);
      console.log(`[TastyOAuth] connect: token_obtained=${!!token}`);

      // Get account info if token worked
      let accountNumber = null;
      if (token) {
        try {
          const acctRes = await fetch('https://api.tastytrade.com/customers/me/accounts', {
            headers: { Authorization: `Bearer ${token.access_token}` }
          });
          const acctJson = await acctRes.json();
          accountNumber = acctJson?.data?.items?.[0]?.account?.['account-number'] || null;
          console.log(`[TastyOAuth] connect: account_number=${accountNumber}`);
        } catch (_) {}
      }

      // Always save credentials regardless of token success
      const { error: upsertErr } = await supabase.from('broker_credentials').upsert({
        user_id,
        broker: 'tastytrade',
        credentials: { 
          refresh_token,
          client_secret,
          access_token: token?.access_token || null,
          account_number: accountNumber,
          expires_at: token ? new Date(Date.now() + token.expires_in * 1000).toISOString() : null
        }
      }, { onConflict: 'user_id,broker' });
      if (upsertErr) throw new Error(`DB save failed: ${upsertErr.message}`);

      if (!token) {
        return new Response(JSON.stringify({ success: true, account: null, warning: 'Credentials saved but token refresh failed — check logs' }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      }

      return new Response(JSON.stringify({ success: true, account: accountNumber }), {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    } catch (err: any) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }

  // Refresh access token using stored refresh token
  if (action === 'refresh') {
    const userId = url.searchParams.get('user_id');
    if (!userId) {
      return new Response(JSON.stringify({ error: 'user_id required' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    try {
      const { data: creds } = await supabase.from('broker_credentials')
        .select('credentials')
        .eq('user_id', userId)
        .eq('broker', 'tastytrade')
        .single();
      
      if (!creds?.credentials?.refresh_token) {
        throw new Error('No refresh token found');
      }

      const token = await getAccessToken(creds.credentials.refresh_token, creds.credentials.client_secret);
      if (!token) throw new Error('Token refresh failed');

      // Update credentials with new access token
      await supabase.from('broker_credentials').update({
        credentials: { ...creds.credentials, access_token: token.access_token, expires_at: new Date(Date.now() + token.expires_in * 1000).toISOString() }
      }).eq('user_id', userId).eq('broker', 'tastytrade');

      return new Response(JSON.stringify({ access_token: token.access_token }), {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    } catch (err: any) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }

  // Get account balance
  if (action === 'balance') {
    const userId = url.searchParams.get('user_id');
    if (!userId) {
      return new Response(JSON.stringify({ error: 'user_id required' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    try {
      const { data: creds } = await supabase.from('broker_credentials')
        .select('credentials')
        .eq('user_id', userId)
        .eq('broker', 'tastytrade')
        .single();
      
      if (!creds?.credentials?.refresh_token) {
        throw new Error('No credentials found');
      }

      // Get fresh access token
      const token = await getAccessToken(creds.credentials.refresh_token, creds.credentials.client_secret);
      if (!token) throw new Error('Token refresh failed');

      // Fetch account balance
      const accountNumber = creds.credentials.account_number;
      const balanceRes = await fetch(`https://api.tastytrade.com/accounts/${accountNumber}/balance`, {
        headers: { Authorization: `Bearer ${token.access_token}` }
      });
      const balanceJson = await balanceRes.json();

      return new Response(JSON.stringify({ 
        balance: balanceJson.data?.['cash-available-to-withdraw'] || balanceJson.data?.['account-value'] || 0,
        account_value: balanceJson.data?.['account-value'] || 0,
        buying_power: balanceJson.data?.['margin-equity'] || balanceJson.data?.['cash-available-to-withdraw'] || 0
      }), {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    } catch (err: any) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }

  // Get option quote (real-time)
  if (action === 'quote') {
    const userId = url.searchParams.get('user_id');
    const symbol = url.searchParams.get('symbol'); // e.g., "SPY" 
    const optionType = url.searchParams.get('type'); // "call" or "put"
    const strike = url.searchParams.get('strike');
    const expiration = url.searchParams.get('expiration'); // YYYY-MM-DD
    
    if (!userId || !symbol || !optionType || !strike || !expiration) {
      return new Response(JSON.stringify({ error: 'user_id, symbol, type, strike, expiration required' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    try {
      const { data: creds } = await supabase.from('broker_credentials')
        .select('credentials')
        .eq('user_id', userId)
        .eq('broker', 'tastytrade')
        .single();
      
      if (!creds?.credentials?.refresh_token) {
        throw new Error('No credentials found');
      }

      // Get fresh access token
      const token = await getAccessToken(creds.credentials.refresh_token, creds.credentials.client_secret);
      if (!token) throw new Error('Token refresh failed');

      // Format option symbol for Tastytrade: SPY 240517 450 C (SPY May 17 2024 $450 Call)
      const expDate = expiration.replace(/-/g, '').slice(2); // YYMMDD
      const strikeNum = Number(strike);
      const optSymbol = `${symbol} ${expDate.slice(0,2)}${expDate.slice(2,4)}${expDate.slice(4)} ${Math.floor(strikeNum)} ${optionType.toLowerCase() === 'call' ? 'C' : 'P'}`;
      
      // Fetch option quote from Tastytrade
      const quoteRes = await fetch(`https://api.tastytrade.com/market-data/quotes?symbol=${encodeURIComponent(optSymbol)}`, {
        headers: { Authorization: `Bearer ${token.access_token}` }
      });
      const quoteJson = await quoteRes.json();
      
      const quote = quoteJson.data?.items?.[0];
      if (!quote) throw new Error('No quote returned');

      return new Response(JSON.stringify({
        bid: quote.bid || 0,
        ask: quote.ask || 0,
        last: quote.last || 0,
        mid: (quote.bid + quote.ask) / 2 || quote.last || 0,
        volume: quote.volume || 0,
        open_interest: quote['open-interest'] || 0,
        source: 'tastytrade'
      }), {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    } catch (err: any) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }

  return new Response(JSON.stringify({ error: 'Invalid action. Use: connect, refresh, balance, or quote' }), {
    status: 400,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' }
  });
});
