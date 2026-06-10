"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.supabase = void 0;
exports.loadAllEnabledBots = loadAllEnabledBots;
exports.loadOpenTrades = loadOpenTrades;
exports.getAlpacaCreds = getAlpacaCreds;
exports.recordTrade = recordTrade;
exports.closeTrade = closeTrade;
exports.updateBotBalance = updateBotBalance;
exports.updateBotLastRun = updateBotLastRun;
exports.incrementDailyTradeCount = incrementDailyTradeCount;
require("dotenv/config");
const supabase_js_1 = require("@supabase/supabase-js");
const ws_1 = __importDefault(require("ws"));
exports.supabase = (0, supabase_js_1.createClient)(process.env.SUPABASE_URL, (process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_KEY), { global: { headers: {} }, realtime: { transport: ws_1.default } });
async function loadAllEnabledBots() {
    const { data, error } = await exports.supabase
        .from('options_bots')
        .select('*')
        .eq('enabled', true)
        .eq('auto_submit', true);
    if (error) {
        console.error('[Supabase] Failed to load bots:', error.message);
        return [];
    }
    return (data || []);
}
async function loadOpenTrades(botId) {
    const { data, error } = await exports.supabase
        .from('options_trades')
        .select('*')
        .eq('bot_id', botId)
        .eq('status', 'open');
    if (error) {
        console.error(`[Supabase] Failed to load open trades for bot ${botId}:`, error.message);
        return [];
    }
    return (data || []);
}
async function getAlpacaCreds(userId) {
    const { data, error } = await exports.supabase
        .from('broker_credentials')
        .select('credentials')
        .eq('user_id', userId)
        .eq('broker', 'alpaca')
        .maybeSingle();
    if (error || !data)
        return null;
    return data.credentials;
}
async function recordTrade(trade) {
    const { error } = await exports.supabase.from('options_trades').insert(trade);
    if (error)
        console.error('[Supabase] Insert trade failed:', error.message);
}
async function closeTrade(tradeId, exitPrice, pnl) {
    const { error } = await exports.supabase
        .from('options_trades')
        .update({ status: 'closed', exit_price: exitPrice, pnl, closed_at: new Date().toISOString() })
        .eq('id', tradeId);
    if (error)
        console.error('[Supabase] Close trade failed:', error.message);
}
async function updateBotBalance(botId, newBalance) {
    const { error } = await exports.supabase
        .from('options_bots')
        .update({ paper_balance: newBalance })
        .eq('id', botId);
    if (error)
        console.error('[Supabase] Update balance failed:', error.message);
}
async function updateBotLastRun(botId) {
    const { error } = await exports.supabase
        .from('options_bots')
        .update({ last_run_at: new Date().toISOString() })
        .eq('id', botId);
    if (error)
        console.error('[Supabase] Update last_run_at failed:', error.message);
}
async function incrementDailyTradeCount(botId, currentCount) {
    const { error } = await exports.supabase
        .from('options_bots')
        .update({ daily_trade_count: currentCount + 1 })
        .eq('id', botId);
    if (error)
        console.error('[Supabase] Increment trade count failed:', error.message);
}
