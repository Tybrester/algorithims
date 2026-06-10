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

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });

  const ip = req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown';
  if (!checkRateLimit(ip)) {
    return new Response(JSON.stringify({ error: 'Too many attempts. Try again in 15 minutes.' }), {
      status: 429, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }

  try {
    const contentLength = Number(req.headers.get('content-length') || 0);
    if (contentLength > 8192) return new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    const rawBody = await req.text();
    if (rawBody.length > 8192) return new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    let parsed: any;
    try { parsed = JSON.parse(rawBody); } catch { return new Response(JSON.stringify({ error: 'Invalid JSON' }), { status: 422, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }); }
    const username = typeof parsed.username === 'string' ? parsed.username.trim().slice(0, 128) : '';
    const password = typeof parsed.password === 'string' ? parsed.password.slice(0, 256) : '';
    const mfa_code = typeof parsed.mfa_code === 'string' ? parsed.mfa_code.replace(/\D/g, '').slice(0, 8) : '';
    const user_id  = typeof parsed.user_id  === 'string' ? parsed.user_id.trim().slice(0, 64) : '';
    if (!username || !password || !user_id) {
      return new Response(JSON.stringify({ error: 'Missing fields' }), {
        status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
    if (!/^[0-9a-f-]{36}$/i.test(user_id)) return new Response(JSON.stringify({ error: 'Invalid user_id' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    // Build session payload
    // Use a consistent device ID based on user_id so it's recognized as same device
    const deviceId = user_id.replace(/-/g, '').substring(0, 16);
    const payload: Record<string, unknown> = { 
      login: username, 
      password, 
      'remember-me': true,
      'device-id': deviceId
    };
    if (mfa_code) payload['one-time-password'] = mfa_code;

    const res = await fetch('https://api.tastytrade.com/sessions', {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'X-Device-Id': deviceId,
        'X-Device-Name': 'BoofCapital-web'
      },
      body: JSON.stringify(payload)
    });

    const json = await res.json();
    
    console.log('[TastyAuth] Response status:', res.status);
    console.log('[TastyAuth] Response body:', JSON.stringify(json));

    // Device/MFA challenge — tell client to ask for code
    if (!res.ok && !json.data?.['session-token']) {
      const errMsg = (json.error?.message || json['error-message'] || '').toLowerCase();
      const errorCode = json.error?.code || '';
      console.log('[TastyAuth] Error message:', errMsg, 'Code:', errorCode);
      
      // Handle device challenge required
      if (errorCode === 'device_challenge_required' || errMsg.includes('device_challenge')) {
        // Store challenge info in Supabase for the verification step
        const challengeToken = res.headers.get('X-Tastyworks-Challenge-Token') || 
                              json.redirect?.headers?.[0] || 
                              'pending';
        
        await supabase.from('oauth_states').upsert({
          user_id: user_id,
          state: 'tasty_challenge_' + user_id,
          challenge_token: challengeToken,
          username: username,
          password: password, // Temporarily store for challenge completion
          created_at: new Date().toISOString()
        }, { onConflict: 'user_id' });
        
        return new Response(JSON.stringify({ 
          mfa_required: true,
          message: 'Device authentication required. Check your email/SMS for a verification code.'
        }), {
          status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      }
      
      // Only treat as MFA if error message contains MFA-related terms
      const needsMfa = errMsg.includes('device') || errMsg.includes('challenge') ||
        errMsg.includes('mfa') || errMsg.includes('verification') || 
        errMsg.includes('two-factor') || errMsg.includes('2fa') ||
        errMsg.includes('security code') || errMsg.includes('login code');
      console.log('[TastyAuth] Needs MFA?', needsMfa);
      if (needsMfa) {
        return new Response(JSON.stringify({ mfa_required: true }), {
          status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      }
      // Otherwise it's invalid credentials
      return new Response(JSON.stringify({ error: json.error?.message || json['error-message'] || 'Invalid credentials' }), {
        status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    let rememberToken = json.data?.['remember-token'] || null;
    let sessionToken = json.data?.['session-token'] || null;

    // Handle device challenge completion if MFA code provided
    if (mfa_code && !sessionToken) {
      // Look up pending challenge
      const { data: challengeData } = await supabase.from('oauth_states')
        .select('*')
        .eq('user_id', user_id)
        .eq('state', 'tasty_challenge_' + user_id)
        .maybeSingle();
      
      if (challengeData) {
        console.log('[TastyAuth] Completing device challenge with code');
        
        // Complete the device challenge
        const challengeRes = await fetch('https://api.tastytrade.com/device-challenge', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Device-Id': deviceId,
            'X-Tastyworks-Challenge-Token': challengeData.challenge_token || ''
          },
          body: JSON.stringify({
            'one-time-password': mfa_code,
            'remember-me': true
          })
        });
        
        const challengeJson = await challengeRes.json();
        console.log('[TastyAuth] Challenge response:', JSON.stringify(challengeJson));
        
        if (challengeJson.data?.['session-token']) {
          // Challenge completed successfully, retry login
          const retryRes = await fetch('https://api.tastytrade.com/sessions', {
            method: 'POST',
            headers: { 
              'Content-Type': 'application/json',
              'X-Device-Id': deviceId,
              'X-Device-Name': 'BoofCapital-web'
            },
            body: JSON.stringify({
              login: username,
              password: password,
              'remember-me': true,
              'device-id': deviceId
            })
          });
          
          const retryJson = await retryRes.json();
          if (retryJson.data?.['session-token']) {
            json.data = retryJson.data;
            // Update tokens for later use
            sessionToken = retryJson.data['session-token'];
            rememberToken = retryJson.data['remember-token'] || null;
          }
        }
        
        // Clean up challenge data
        await supabase.from('oauth_states').delete().eq('user_id', user_id).eq('state', 'tasty_challenge_' + user_id);
      }
    }

    // Get account number
    let accountNumber = null;
    if (json.data?.['session-token']) {
      try {
        const acctRes = await fetch('https://api.tastytrade.com/customers/me/accounts', {
          headers: { Authorization: json.data['session-token'] }
        });
        const acctJson = await acctRes.json();
        accountNumber = acctJson?.data?.items?.[0]?.account?.['account-number'] || null;
      } catch (_) {
        // Ignore account fetch errors
      }
    }

    // Save credentials to Supabase (including session token to stay logged in)
    await supabase.from('broker_credentials').upsert({
      user_id,
      broker: 'tastytrade',
      credentials: { 
        username, 
        password, 
        remember_token: rememberToken,
        session_token: sessionToken,
        account_number: accountNumber,
        session_created_at: new Date().toISOString()
      }
    }, { onConflict: 'user_id,broker' });

    return new Response(JSON.stringify({ success: true, username, session_token: sessionToken }), {
      status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
});
