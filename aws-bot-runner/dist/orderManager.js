"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getOptionMidPrice = getOptionMidPrice;
exports.placeOrder = placeOrder;
const supabaseClient_1 = require("./supabaseClient");
const BUFFER = 0.02;
const LIMIT_TIMEOUT_MS = 5000;
function getBaseUrl(env, forcePaper) {
    return (!forcePaper && env === 'live')
        ? 'https://api.alpaca.markets'
        : 'https://paper-api.alpaca.markets';
}
function formatOptionSymbol(symbol, expDate, optType, strike) {
    const d = new Date(expDate);
    const yy = String(d.getUTCFullYear()).slice(2);
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
    const dd = String(d.getUTCDate()).padStart(2, '0');
    const typeChar = optType === 'call' ? 'C' : 'P';
    const strikeStr = String(Math.round(strike * 1000)).padStart(8, '0');
    return `${symbol.toUpperCase()}${yy}${mm}${dd}${typeChar}${strikeStr}`;
}
async function alpacaFetch(url, apiKey, secretKey, method = 'GET', body) {
    const res = await fetch(url, {
        method,
        headers: {
            'APCA-API-KEY-ID': apiKey,
            'APCA-API-SECRET-KEY': secretKey,
            'Content-Type': 'application/json',
        },
        body: body ? JSON.stringify(body) : undefined,
    });
    return { ok: res.ok, status: res.status, data: await res.json() };
}
async function getOptionMidPrice(apiKey, secretKey, optionSymbol, baseUrl) {
    try {
        const url = `${baseUrl}/v1beta1/options/snapshots/${encodeURIComponent(optionSymbol)}`;
        const { ok, data } = await alpacaFetch(url, apiKey, secretKey);
        if (!ok || !data?.snapshot)
            return null;
        const quote = data.snapshot.latestQuote;
        if (quote?.bp && quote?.ap) {
            return Math.round(((quote.bp + quote.ap) / 2) * 100) / 100;
        }
        return null;
    }
    catch {
        return null;
    }
}
async function placeOrder(userId, symbol, expDate, optType, strike, side, qty, forcePaper, midPrice) {
    const creds = await (0, supabaseClient_1.getAlpacaCreds)(userId);
    if (!creds)
        return { success: false, error: 'No Alpaca credentials' };
    const { api_key, secret_key, env } = creds;
    const baseUrl = getBaseUrl(env, forcePaper);
    const optionSymbol = formatOptionSymbol(symbol, expDate, optType, strike);
    const limitPrice = midPrice && midPrice > 0
        ? (side === 'buy'
            ? Math.round((midPrice + BUFFER) * 100) / 100
            : Math.round((midPrice - BUFFER) * 100) / 100)
        : null;
    const orderBody = {
        symbol: optionSymbol,
        side,
        type: limitPrice ? 'limit' : 'market',
        time_in_force: 'day',
        qty: String(qty),
        ...(limitPrice ? { limit_price: String(limitPrice.toFixed(2)) } : {}),
    };
    console.log(`[Order] ${side.toUpperCase()} ${qty}x ${optionSymbol} type=${orderBody.type} limit=${limitPrice ?? 'n/a'}`);
    const { ok, data: order } = await alpacaFetch(`${baseUrl}/v2/orders`, api_key, secret_key, 'POST', orderBody);
    if (!ok) {
        console.error(`[Order] Failed:`, order.message || order);
        return { success: false, error: order.message || 'Order failed', status: 'failed' };
    }
    let fillPrice = order.filled_avg_price ? Number(order.filled_avg_price) : undefined;
    let finalOrderId = order.id;
    let finalStatus = order.status;
    if (!fillPrice && order.status !== 'filled' && limitPrice) {
        await new Promise(r => setTimeout(r, LIMIT_TIMEOUT_MS));
        const { ok: pollOk, data: polled } = await alpacaFetch(`${baseUrl}/v2/orders/${order.id}`, api_key, secret_key);
        if (pollOk && polled.filled_avg_price) {
            fillPrice = Number(polled.filled_avg_price);
            finalStatus = polled.status;
            console.log(`[Order] Limit filled at $${fillPrice}`);
        }
        else {
            console.log(`[Order] Limit unfilled after ${LIMIT_TIMEOUT_MS}ms, cancelling and falling back to market`);
            await alpacaFetch(`${baseUrl}/v2/orders/${order.id}`, api_key, secret_key, 'DELETE');
            const mktBody = { symbol: optionSymbol, side, type: 'market', time_in_force: 'day', qty: String(qty) };
            const { ok: mktOk, data: mktOrder } = await alpacaFetch(`${baseUrl}/v2/orders`, api_key, secret_key, 'POST', mktBody);
            if (mktOk) {
                finalOrderId = mktOrder.id;
                finalStatus = mktOrder.status;
                fillPrice = mktOrder.filled_avg_price ? Number(mktOrder.filled_avg_price) : undefined;
                console.log(`[Order] Market fallback placed: ${mktOrder.id} status=${mktOrder.status}`);
                if (!fillPrice) {
                    await new Promise(r => setTimeout(r, 2000));
                    const { data: mktPolled } = await alpacaFetch(`${baseUrl}/v2/orders/${mktOrder.id}`, api_key, secret_key);
                    if (mktPolled.filled_avg_price)
                        fillPrice = Number(mktPolled.filled_avg_price);
                }
            }
            else {
                console.error('[Order] Market fallback failed:', mktOrder.message);
                return { success: false, error: mktOrder.message || 'Market fallback failed', status: 'failed' };
            }
        }
    }
    return { success: true, orderId: finalOrderId, fillPrice, status: finalStatus };
}
