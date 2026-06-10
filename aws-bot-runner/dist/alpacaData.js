"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.fetchCandles = fetchCandles;
exports.getOptionSnapshot = getOptionSnapshot;
function toAlpacaTimeframe(tf) {
    return tf.replace(/^(\d+)m$/, '$1Min').replace(/^(\d+)h$/, '$1Hour').replace(/^(\d+)d$/, '$1Day');
}
async function fetchCandles(symbol, timeframe, limit, apiKey, secretKey, usePaper = false) {
    const baseUrl = 'https://data.alpaca.markets';
    const tf = toAlpacaTimeframe(timeframe);
    const url = `${baseUrl}/v2/stocks/${symbol}/bars?timeframe=${tf}&limit=${limit}&adjustment=raw&feed=iex`;
    console.log(`[AlpacaData] GET ${url}`);
    const res = await fetch(url, {
        headers: {
            'APCA-API-KEY-ID': apiKey,
            'APCA-API-SECRET-KEY': secretKey,
        },
    });
    if (!res.ok) {
        console.error(`[AlpacaData] fetchCandles ${symbol} ${timeframe} failed: ${res.status}`);
        return [];
    }
    const json = await res.json();
    const bars = json.bars || [];
    return bars.map((b) => ({
        time: new Date(b.t).getTime(),
        open: b.o,
        high: b.h,
        low: b.l,
        close: b.c,
        volume: b.v,
    }));
}
async function getOptionSnapshot(optionSymbol, apiKey, secretKey, usePaper = false) {
    const baseUrl = usePaper ? 'https://data.sandbox.alpaca.markets' : 'https://data.alpaca.markets';
    const url = `${baseUrl}/v1beta1/options/snapshots/${encodeURIComponent(optionSymbol)}`;
    try {
        const res = await fetch(url, {
            headers: {
                'APCA-API-KEY-ID': apiKey,
                'APCA-API-SECRET-KEY': secretKey,
            },
        });
        if (!res.ok)
            return null;
        const json = await res.json();
        const q = json.snapshot?.latestQuote;
        if (!q)
            return null;
        const bid = Number(q.bp || 0);
        const ask = Number(q.ap || 0);
        return { bid, ask, mid: Math.round(((bid + ask) / 2) * 100) / 100 };
    }
    catch {
        return null;
    }
}
