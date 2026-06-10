// Tastytrade Health Check - Runs daily to verify connection
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const ALLOWED_ORIGINS = ['https://boofcapital.com', 'https://www.boofcapital.com', 'http://localhost:3000'];
function getCorsHeaders(req: Request) {
  const origin = req.headers.get('origin') || '';
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return { 'Access-Control-Allow-Origin': allowed, 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };
}
const corsHeaders = { 'Access-Control-Allow-Origin': 'https://boofcapital.com', 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });

  try {
    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    // Get all users with Tastytrade credentials
    const { data: credentials } = await supabase
      .from('broker_credentials')
      .select('user_id, credentials')
      .eq('broker', 'tastytrade');

    if (!credentials || credentials.length === 0) {
      return new Response(JSON.stringify({ 
        status: 'warning', 
        message: 'No Tastytrade credentials found for any users' 
      }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    }

    const results = [];
    let healthyCount = 0;
    let failedCount = 0;

    for (const cred of credentials) {
      try {
        // Test the OAuth refresh
        const response = await fetch(
          `${Deno.env.get('SUPABASE_URL')}/functions/v1/tasty-oauth?action=refresh&user_id=${cred.user_id}`,
          { headers: { 'Authorization': `Bearer ${Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')}` } }
        );
        
        const result = await response.json();
        
        if (result.access_token) {
          healthyCount++;
          results.push({ user_id: cred.user_id, status: 'healthy' });
        } else {
          failedCount++;
          results.push({ user_id: cred.user_id, status: 'failed', error: result.error });
          
          // Log the failure for monitoring
          await supabase.from('connection_health_logs').insert({
            user_id: cred.user_id,
            broker: 'tastytrade',
            status: 'failed',
            error: result.error || 'Unknown error',
            checked_at: new Date().toISOString()
          });
        }
      } catch (err) {
        failedCount++;
        results.push({ user_id: cred.user_id, status: 'error', error: err.message });
      }
    }

    return new Response(JSON.stringify({
      status: failedCount > 0 ? 'warning' : 'healthy',
      timestamp: new Date().toISOString(),
      summary: { total: credentials.length, healthy: healthyCount, failed: failedCount },
      results
    }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

  } catch (err) {
    return new Response(JSON.stringify({ 
      status: 'error', 
      message: err.message 
    }), { 
      status: 500, 
      headers: { ...corsHeaders, 'Content-Type': 'application/json' } 
    });
  }
});
