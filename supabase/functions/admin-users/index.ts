const ALLOWED_ORIGINS = ['https://boofcapital.com', 'https://www.boofcapital.com', 'http://localhost:3000', 'http://127.0.0.1:3000', 'http://127.0.0.1:60078'];
function getCorsHeaders(req: Request) {
  const origin = req.headers.get('origin') || '';
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return { 'Access-Control-Allow-Origin': allowed, 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };
}

const ADMIN_USER_ID = 'd0bb84ba-f968-446c-9792-9bcff8849e37';

Deno.serve(async (req) => {
  const corsHeaders = getCorsHeaders(req);
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });

  try {
    const authHeader = req.headers.get('Authorization');
    if (!authHeader) return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: corsHeaders });

    // Verify caller is the admin
    const supabaseUrl = Deno.env.get('SUPABASE_URL')!;
    const serviceKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
    const anonKey = Deno.env.get('SUPABASE_ANON_KEY')!;

    // Get calling user from their JWT
    const { createClient } = await import('https://esm.sh/@supabase/supabase-js@2');
    const userClient = createClient(supabaseUrl, anonKey, {
      global: { headers: { Authorization: authHeader } },
    });
    const { data: { user }, error: userErr } = await userClient.auth.getUser();
    if (userErr || !user) return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: corsHeaders });
    if (user.id !== ADMIN_USER_ID) return new Response(JSON.stringify({ error: 'Forbidden' }), { status: 403, headers: corsHeaders });

    const adminClient = createClient(supabaseUrl, serviceKey);
    const body = req.method === 'POST' ? await req.json().catch(() => ({})) : {};
    const action = body.action || 'list';

    // Approve a user — send invite email so user sets their own password (no plaintext password stored)
    if (action === 'approve') {
      const email = typeof body.email === 'string' ? body.email.trim().slice(0, 200) : '';
      if (!email) return new Response(JSON.stringify({ error: 'email required' }), { status: 400, headers: corsHeaders });
      console.log(`[admin-users] Approving user: ${email}`);

      // Get access request for name metadata
      const { data: request } = await adminClient
        .from('access_requests')
        .select('name')
        .eq('email', email)
        .single();

      const fullName = request?.name || '';

      // Send invite email — user clicks link and sets their own password
      const { data, error: inviteErr } = await adminClient.auth.admin.inviteUserByEmail(email, {
        data: { approved: true, full_name: fullName }
      });

      if (inviteErr) {
        console.error(`[admin-users] Failed to invite ${email}:`, inviteErr);
        return new Response(JSON.stringify({ error: inviteErr.message }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
      }

      // Update access request status
      await adminClient
        .from('access_requests')
        .update({ status: 'approved', reviewed_at: new Date().toISOString() })
        .eq('email', email);

      console.log(`[admin-users] Invite sent to ${email}, ID: ${data.user?.id}`);
      return new Response(JSON.stringify({ ok: true }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    }

    // Delete a user
    if (action === 'delete') {
      const email = typeof body.email === 'string' ? body.email.trim().slice(0, 200) : '';
      if (!email) return new Response(JSON.stringify({ error: 'email required' }), { status: 400, headers: corsHeaders });
      console.log(`[admin-users] Deleting user: ${email}`);
      
      // Get user ID from email
      const { data: users } = await adminClient.auth.admin.listUsers({ perPage: 1000 });
      const user = users.find(u => u.email === email);
      if (!user) {
        return new Response(JSON.stringify({ error: 'User not found' }), { status: 404, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
      }
      
      // Delete from users table
      await adminClient.from('users').delete().eq('id', user.id);
      
      // Delete from auth
      const { error: deleteErr } = await adminClient.auth.admin.deleteUser(user.id);
      if (deleteErr) {
        console.error(`[admin-users] Failed to delete user ${email}:`, deleteErr);
        return new Response(JSON.stringify({ error: deleteErr.message }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
      }
      
      console.log(`[admin-users] User ${email} deleted`);
      return new Response(JSON.stringify({ ok: true }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    }

    // Default: list all users
    const { data: { users }, error } = await adminClient.auth.admin.listUsers({ perPage: 1000 });
    if (error) throw error;

    const result = users.map(u => ({ id: u.id, email: u.email, created_at: u.created_at }));
    return new Response(JSON.stringify({ users: result }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

  } catch (e) {
    return new Response(JSON.stringify({ error: String(e) }), { status: 500, headers: corsHeaders });
  }
});
