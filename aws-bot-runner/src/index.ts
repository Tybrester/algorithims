import 'dotenv/config';
import { loadAllEnabledBots, BotConfig, supabase } from './supabaseClient';
import { runBot, checkExits } from './botRunner';

const SIGNAL_INTERVAL_MS = 60_000;   // run signals every 60s
const EXIT_INTERVAL_MS   = 30_000;   // check exits every 30s
const BOT_RELOAD_MS      = 60_000;   // reload bot configs every 60s

let bots: BotConfig[] = [];
let isRunning = false;

async function reloadBots(): Promise<void> {
  try {
    const loaded = await loadAllEnabledBots();
    bots = loaded;
    console.log(`[Runner] Loaded ${bots.length} enabled bots: ${bots.map(b => b.name).join(', ')}`);
  } catch (err) {
    console.error('[Runner] Failed to reload bots:', err);
  }
}

async function resetDailyCounts(): Promise<void> {
  const etStr = new Date().toLocaleString('en-US', { timeZone: 'America/New_York' });
  const et = new Date(etStr);
  if (et.getHours() === 9 && et.getMinutes() < 2) {
    console.log('[Runner] Resetting daily trade counts...');
    await supabase.from('options_bots').update({ daily_trade_count: 0 }).neq('id', '00000000-0000-0000-0000-000000000000');
  }
}

async function signalLoop(): Promise<void> {
  if (isRunning) return;
  isRunning = true;
  try {
    await resetDailyCounts();
    const activeBots = bots.filter(b => b.enabled && b.auto_submit);
    if (!activeBots.length) { isRunning = false; return; }

    console.log(`[Runner] Running signals for ${activeBots.length} bots at ${new Date().toISOString()}`);
    await Promise.allSettled(activeBots.map(bot => runBot(bot)));
  } catch (err) {
    console.error('[Runner] Signal loop error:', err);
  } finally {
    isRunning = false;
  }
}

async function exitLoop(): Promise<void> {
  const activeBots = bots.filter(b => b.enabled);
  if (!activeBots.length) return;
  await Promise.allSettled(activeBots.map(bot => checkExits(bot)));
}

async function main(): Promise<void> {
  console.log('═══════════════════════════════════════════');
  console.log(' Boof Capital AWS Bot Runner — us-east-1');
  console.log(`  Supabase: ${process.env.SUPABASE_URL}`);
  console.log('═══════════════════════════════════════════');

  await reloadBots();

  // Bot config reload loop
  setInterval(reloadBots, BOT_RELOAD_MS);

  // Signal loop
  setInterval(signalLoop, SIGNAL_INTERVAL_MS);

  // Exit check loop
  setInterval(exitLoop, EXIT_INTERVAL_MS);

  // Run immediately on startup
  await signalLoop();

  console.log('[Runner] All loops started. Bot runner is live.');
}

main().catch(err => {
  console.error('[Runner] Fatal error:', err);
  process.exit(1);
});
