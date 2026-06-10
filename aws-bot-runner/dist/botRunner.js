"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.runBot = runBot;
exports.checkExits = checkExits;
const supabaseClient_1 = require("./supabaseClient");
const alpacaData_1 = require("./alpacaData");
const orderManager_1 = require("./orderManager");
// ── Signal imports (same files as edge function, Node-compatible) ──
const boof22_1 = require("./signals/boof22");
const boof22_v2_1 = require("./signals/boof22_v2");
const boof23_1 = require("./signals/boof23");
const boof23_v2_1 = require("./signals/boof23_v2");
const boof24_1 = require("./signals/boof24");
const activeLocks = new Set(); // in-memory lock: bot_id:symbol
const R = 0.05;
// ── Black-Scholes for option pricing ──
function blackScholes(S, K, T, r, sigma, type) {
    if (T <= 0 || sigma <= 0)
        return Math.max(0, type === 'call' ? S - K : K - S);
    const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
    const d2 = d1 - sigma * Math.sqrt(T);
    const N = (x) => {
        const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741, a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
        const sign = x < 0 ? -1 : 1;
        const absX = Math.abs(x);
        const t2 = 1 / (1 + p * absX);
        return 0.5 * (1 + sign * (1 - (((((a5 * t2 + a4) * t2) + a3) * t2 + a2) * t2 + a1) * t2 * Math.exp(-absX * absX / 2)));
    };
    return type === 'call'
        ? S * N(d1) - K * Math.exp(-r * T) * N(d2)
        : K * Math.exp(-r * T) * N(-d2) - S * N(-d1);
}
function calcHistVol(closes, period = 20) {
    if (closes.length < period + 1)
        return 0.3;
    const slice = closes.slice(-period - 1);
    const rets = slice.slice(1).map((c, i) => Math.log(c / slice[i]));
    const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
    const variance = rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length;
    return Math.sqrt(variance * 252 * 390);
}
function nearestFriday(expType) {
    const now = new Date();
    const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
    if (expType === '0dte') {
        const d = et.getDay();
        if (d === 0)
            et.setDate(et.getDate() + 1);
        if (d === 6)
            et.setDate(et.getDate() + 2);
        return et.toISOString().slice(0, 10);
    }
    const day = et.getDay();
    const daysUntilFri = (5 - day + 7) % 7 || 7;
    et.setDate(et.getDate() + daysUntilFri);
    return et.toISOString().slice(0, 10);
}
function pickStrike(spotPrice, optType, atr) {
    const offset = optType === 'call' ? atr * 0.5 : -atr * 0.5;
    const raw = spotPrice + offset;
    return Math.round(raw);
}
function getScanList(mode) {
    const LISTS = {
        'boof22': ['NVDA', 'AAPL', 'META', 'GOOG', 'MSFT', 'AMZN', 'AMD'],
        'boof22_etf': ['NVDA', 'AAPL', 'META', 'GOOG', 'MSFT', 'AMZN', 'AMD', 'QQQ', 'SPY'],
        'boof23': ['NVDA', 'AAPL', 'META', 'GOOG', 'AMD'],
        'boof23_etf': ['NVDA', 'AAPL', 'META', 'GOOG', 'AMD', 'QQQ', 'SPY'],
        'boof24': ['NVDA', 'AAPL', 'META', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'TSLA', 'LLY', 'PLTR'],
        'scan_duo': ['SPY', 'QQQ'],
        'boofinator': ['SPY', 'QQQ', 'TSLA', 'NVDA', 'COIN', 'PLTR', 'AMD', 'AAPL', 'AMZN', 'META', 'GOOG'],
    };
    return LISTS[mode] || LISTS['boof22'];
}
function isMarketOpen() {
    const now = new Date();
    const etStr = now.toLocaleString('en-US', { timeZone: 'America/New_York' });
    const et = new Date(etStr);
    const day = et.getDay();
    if (day === 0 || day === 6)
        return false;
    const h = et.getHours(), m = et.getMinutes();
    const afterOpen = h > 9 || (h === 9 && m >= 30);
    const beforeClose = h < 15 || (h === 15 && m <= 58);
    return afterOpen && beforeClose;
}
async function runBot(bot) {
    if (!isMarketOpen())
        return;
    const creds = await (0, supabaseClient_1.getAlpacaCreds)(bot.user_id);
    if (!creds) {
        console.warn(`[Bot:${bot.name}] No Alpaca creds`);
        return;
    }
    const isPaper = false; // paper keys use regular data.alpaca.markets, not sandbox
    const interval = bot.bot_interval || '5m';
    const symbols = (bot.bot_symbol && bot.bot_symbol !== 'SCAN') ? [bot.bot_symbol] : getScanList(bot.bot_scan_mode);
    const expType = bot.bot_expiry_type || 'weekly';
    for (const sym of symbols) {
        try {
            // In-memory lock: skip if another bot is currently entering this symbol
            const lockKey = `${bot.id}:${sym}`;
            if (activeLocks.has(lockKey))
                continue;
            // Skip if bot already has an open trade for this symbol
            const { data: openCheck } = await supabaseClient_1.supabase
                .from('options_trades')
                .select('id')
                .eq('bot_id', bot.id)
                .eq('symbol', sym)
                .eq('status', 'open')
                .limit(1);
            if (openCheck && openCheck.length > 0)
                continue;
            activeLocks.add(lockKey);
            const candles = await (0, alpacaData_1.fetchCandles)(sym, interval, 150, creds.api_key, creds.secret_key, isPaper);
            if (candles.length < 50)
                continue;
            const spotPrice = candles[candles.length - 1].close;
            const tpPct = Number(bot.take_profit_pct ?? 40) / 100;
            const slPct = Math.abs(Number(bot.stop_loss_pct ?? 15)) / 100;
            let signal = 'none';
            let reason = '';
            let slack = 1.0;
            const sig = bot.bot_signal;
            if (sig === 'boof22' || sig === 'boof22_5') {
                const result = (0, boof22_1.getBoof22Signal)(candles, sym, tpPct, slPct);
                signal = result.signal;
                reason = result.reason;
                slack = result.slack ?? 1.0;
            }
            else if (sig === 'boof22_v2') {
                const result = (0, boof22_v2_1.getBoof22v2Signal)(candles, sym, tpPct, slPct);
                signal = result.signal;
                reason = result.reason;
                slack = result.slack ?? 1.0;
            }
            else if (sig === 'boof23' || sig === 'boof23_5') {
                const result = (0, boof23_1.getBoof23Signal)(candles, sym, tpPct, slPct);
                signal = result.signal;
                reason = result.reason;
                slack = result.slack ?? 1.0;
            }
            else if (sig === 'boof23_v2') {
                const result = (0, boof23_v2_1.getBoof23v2Signal)(candles, sym, tpPct, slPct);
                signal = result.signal;
                reason = result.reason;
                slack = result.slack ?? 1.0;
            }
            else if (sig === 'boof24') {
                const result = (0, boof24_1.getBoof24Signal)(candles, sym, tpPct, slPct);
                signal = result.signal;
                reason = result.reason;
                slack = result.slack ?? 1.0;
            }
            if (signal === 'none')
                continue;
            // Max daily trades guard
            if (bot.max_daily_trades && bot.daily_trade_count >= bot.max_daily_trades) {
                console.log(`[Bot:${bot.name}] Max daily trades reached`);
                return;
            }
            const optType = signal === 'buy' ? 'call' : 'put';
            if (bot.option_type === 'call' && optType !== 'call')
                continue;
            if (bot.option_type === 'put' && optType !== 'put')
                continue;
            const sigma = calcHistVol(candles.map(c => c.close));
            const atrs = candles.map((c, i) => {
                if (i === 0)
                    return c.high - c.low;
                return Math.max(c.high - c.low, Math.abs(c.high - candles[i - 1].close), Math.abs(c.low - candles[i - 1].close));
            });
            const atr = atrs.slice(-14).reduce((a, b) => a + b) / 14;
            const strike = pickStrike(spotPrice, optType, atr);
            const expDate = nearestFriday(expType);
            const T = Math.max(0, (new Date(expDate).getTime() - Date.now()) / (365 * 24 * 60 * 60 * 1000));
            let premium = blackScholes(spotPrice, strike, T, R, sigma, optType);
            if (premium <= 0.01)
                premium = 0.05;
            const amount = Number(bot.amount_per_trade ?? 1000);
            const contracts = Math.max(1, Math.floor(amount / (premium * 100)));
            console.log(`[Bot:${bot.name}] SIGNAL ${signal.toUpperCase()} ${sym} ${optType} $${strike} exp=${expDate} premium=$${premium.toFixed(2)} contracts=${contracts} reason=${reason}`);
            const orderResult = await (0, orderManager_1.placeOrder)(bot.user_id, sym, expDate, optType, strike, 'buy', contracts, isPaper, premium);
            const fillPremium = orderResult.fillPrice ?? premium;
            const totalCost = fillPremium * contracts * 100;
            const tradeStatus = orderResult.success ? (orderResult.status === 'filled' ? 'open' : 'pending') : 'failed';
            await (0, supabaseClient_1.recordTrade)({
                bot_id: bot.id,
                user_id: bot.user_id,
                symbol: sym,
                option_type: optType,
                strike,
                expiration_date: expDate,
                premium_per_contract: fillPremium,
                entry_price: fillPremium,
                total_cost: totalCost,
                contracts,
                status: tradeStatus,
                created_at: new Date().toISOString(),
                reason,
                entry_slack: slack,
                signal_version: bot.bot_signal,
                broker: bot.broker || 'alpaca_paper',
            });
            activeLocks.delete(lockKey);
            if (tradeStatus !== 'failed') {
                const bal = Number(bot.paper_balance ?? 100000);
                await (0, supabaseClient_1.updateBotBalance)(bot.id, bal - totalCost);
                await (0, supabaseClient_1.incrementDailyTradeCount)(bot.id, bot.daily_trade_count ?? 0);
                bot.paper_balance = bal - totalCost;
                bot.daily_trade_count = (bot.daily_trade_count ?? 0) + 1;
            }
        }
        catch (err) {
            activeLocks.delete(`${bot.id}:${sym}`);
            console.error(`[Bot:${bot.name}] Error on ${sym}:`, err);
        }
    }
    await (0, supabaseClient_1.updateBotLastRun)(bot.id);
}
async function checkExits(bot) {
    const openTrades = await (0, supabaseClient_1.loadOpenTrades)(bot.id);
    if (!openTrades.length)
        return;
    const creds = await (0, supabaseClient_1.getAlpacaCreds)(bot.user_id);
    if (!creds)
        return;
    const isPaper = false; // paper keys use regular data.alpaca.markets, not sandbox
    const interval = bot.bot_interval || '5m';
    const tpPct = Number(bot.take_profit_pct ?? 40) / 100;
    const slPct = Math.abs(Number(bot.stop_loss_pct ?? 15)) / 100;
    for (const trade of openTrades) {
        try {
            const candles = await (0, alpacaData_1.fetchCandles)(trade.symbol, interval, 60, creds.api_key, creds.secret_key, isPaper);
            if (!candles.length)
                continue;
            const spotPrice = candles[candles.length - 1].close;
            const sigma = calcHistVol(candles.map(c => c.close));
            const expDate = new Date(trade.expiration_date);
            const T = Math.max(0, (expDate.getTime() - Date.now()) / (365 * 24 * 60 * 60 * 1000));
            let optionPrice = blackScholes(spotPrice, trade.strike, T, R, sigma, trade.option_type);
            if (optionPrice <= 0)
                optionPrice = Number(trade.premium_per_contract) * 0.1;
            const entryPremium = Number(trade.premium_per_contract);
            const pnlPct = (optionPrice - entryPremium) / entryPremium;
            const pnl = (optionPrice - entryPremium) * trade.contracts * 100;
            const shouldTP = pnlPct >= tpPct;
            const shouldSL = pnlPct <= -slPct;
            const etStr = new Date().toLocaleString('en-US', { timeZone: 'America/New_York' });
            const etNow = new Date(etStr);
            const isEOD = etNow.getHours() >= 15 && etNow.getMinutes() >= 45;
            if (!shouldTP && !shouldSL && !isEOD)
                continue;
            const closeReason = shouldTP ? 'TP' : shouldSL ? 'SL' : 'EOD';
            console.log(`[Bot:${bot.name}] EXIT ${trade.symbol} ${trade.option_type} reason=${closeReason} pnl=$${pnl.toFixed(2)}`);
            if (bot.broker !== 'paper') {
                await (0, orderManager_1.placeOrder)(bot.user_id, trade.symbol, trade.expiration_date, trade.option_type, trade.strike, 'sell', trade.contracts, isPaper, optionPrice);
            }
            await (0, supabaseClient_1.closeTrade)(trade.id, optionPrice, pnl);
            const bal = Number(bot.paper_balance ?? 100000);
            await (0, supabaseClient_1.updateBotBalance)(bot.id, bal + Number(trade.total_cost) + pnl);
            bot.paper_balance = bal + Number(trade.total_cost) + pnl;
        }
        catch (err) {
            console.error(`[Bot:${bot.name}] Exit check error for trade ${trade.id}:`, err);
        }
    }
}
