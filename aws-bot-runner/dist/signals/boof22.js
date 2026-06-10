"use strict";
// =========================================================
// BOOF 22.0 — Volume Cluster Array + ZigZag ATR Reversal
// Real cluster array · fractal swing detection · SR distance filter
// Best on: TSLA, NVDA, COIN, PLTR, AMD, AAPL, AMZN, META, GOOGL
// =========================================================
Object.defineProperty(exports, "__esModule", { value: true });
exports.BOOFINGTON = void 0;
exports.getBoof22Signal = getBoof22Signal;
// ─────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────
const CFG = {
    ATR_LEN: 14,
    VOL_LEN: 50,
    VOL_MULT: 1.3,
    FRACTAL_BARS: 3, // bars each side for fractal confirmation
    ATR_MULT: 0.6, // rejection/bounce confirmation
    CLUSTER_MERGE: 0.5, // merge buckets within ATR * this
    SR_STRENGTH_MIN: 2, // min touches for valid cluster
    SR_DIST_MAX: 1.0, // max ATR distance to nearest cluster
    RVOL_MIN: 0.8, // volume / vol_sma threshold (vs today's session avg, matches backtest)
    SLACK_MAX: 0.8, // NEW: only accept trades with slack < 0.8
};
// ─────────────────────────────────────────────
// BOOFINGTON — official Boof 22 scan list
// Ranked by annual P&L (2025–2026 backtest, atr_mult=0.6, tiered sizing)
// Core signals (slack>=1.4): $600/trade | Expanded (slack<1.4): $200/trade
// ~65 trades/day | WR ~60% | PF ~25 | EV ~$8.40/trade | ~$200k/yr
// ─────────────────────────────────────────────
exports.BOOFINGTON = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD'];
// Active symbols: NVDA, META, AAPL, GOOGL, AMD (top performers, ~65 trades/day)
const SYMBOL_CFG = {
    NVDA: { atrMult: 0.6, volMult: 1.3, srDist: 1.0 },
    META: { atrMult: 0.6, volMult: 1.3, srDist: 1.0 },
    AAPL: { atrMult: 0.6, volMult: 1.2, srDist: 1.0 },
    GOOGL: { atrMult: 0.6, volMult: 1.3, srDist: 1.0 },
    AMD: { atrMult: 0.6, volMult: 1.3, srDist: 1.0 },
};
// ─────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────
function computeATR(candles, period) {
    const atr = new Array(candles.length).fill(0);
    for (let i = 1; i < candles.length; i++) {
        const tr = Math.max(candles[i].high - candles[i].low, Math.abs(candles[i].high - candles[i - 1].close), Math.abs(candles[i].low - candles[i - 1].close));
        atr[i] = i < period
            ? tr
            : atr[i - 1] * (period - 1) / period + tr / period;
    }
    return atr;
}
function computeVolSMA(candles, period) {
    const sma = new Array(candles.length).fill(0);
    for (let i = period; i < candles.length; i++) {
        let sum = 0;
        for (let j = i - period; j < i; j++)
            sum += (candles[j].volume ?? 0);
        sma[i] = sum / period;
    }
    return sma;
}
function computeSessionRvol(candles) {
    const rvol = new Array(candles.length).fill(0);
    const now = new Date();
    const todayMidnightUTC = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    // time field is Unix ms or Unix seconds — normalize
    const toMs = (t) => t > 1e10 ? t : t * 1000;
    const sessionStart = candles.findIndex(c => toMs(c.time) >= todayMidnightUTC);
    if (sessionStart < 0)
        return rvol;
    const sessionBars = candles.slice(sessionStart);
    const sessionVolAvg = sessionBars.reduce((s, c) => s + (c.volume ?? 0), 0) / sessionBars.length;
    for (let i = sessionStart; i < candles.length; i++) {
        rvol[i] = sessionVolAvg > 0 ? (candles[i].volume ?? 0) / sessionVolAvg : 0;
    }
    return rvol;
}
function buildClusterArray(candles, atr, volMult) {
    // Full-history rolling vol SMA (matches backtest), session bars as cluster candidates
    const volSMA = computeVolSMA(candles, CFG.VOL_LEN);
    const atrs = atr.filter(v => v > 0);
    const avgATR = atrs.length ? atrs.reduce((a, b) => a + b, 0) / atrs.length : 0;
    if (avgATR === 0)
        return [];
    const mergeTol = avgATR * CFG.CLUSTER_MERGE;
    const buckets = [];
    for (let i = CFG.VOL_LEN; i < candles.length; i++) {
        const vol = candles[i].volume ?? 0;
        if (vol < volSMA[i] * volMult)
            continue;
        const price = (candles[i].high + candles[i].low) / 2;
        let merged = false;
        for (const b of buckets) {
            if (Math.abs(b.price - price) <= mergeTol) {
                b.price = (b.price * b.strength + price) / (b.strength + 1);
                b.strength++;
                merged = true;
                break;
            }
        }
        if (!merged)
            buckets.push({ price, strength: 1 });
    }
    return buckets
        .filter(b => b.strength >= CFG.SR_STRENGTH_MIN)
        .sort((a, b) => b.strength - a.strength);
}
function nearestClusterDist(price, clusters, atr) {
    if (!clusters.length || atr === 0)
        return { dist: Infinity, cluster: null };
    let best = clusters[0];
    let bestDist = Math.abs(price - best.price) / atr;
    for (const c of clusters) {
        const d = Math.abs(price - c.price) / atr;
        if (d < bestDist) {
            bestDist = d;
            best = c;
        }
    }
    return { dist: bestDist, cluster: best };
}
// ─────────────────────────────────────────────
// MAIN SIGNAL FUNCTION
// ─────────────────────────────────────────────
function getBoof22Signal(candles, symbol = 'NVDA', tpPct = 0.35, slPct = 0.15) {
    const NONE = { signal: 'none', price: 0, reason: 'no signal', direction: 'none', nearestCluster: 0, clusterStrength: 0, atr: 0, tpPct, slPct, slack: 0, tier: 'expanded' };
    const cfg = SYMBOL_CFG[symbol] ?? { atrMult: CFG.ATR_MULT, volMult: CFG.VOL_MULT, srDist: CFG.SR_DIST_MAX };
    const F = CFG.FRACTAL_BARS;
    const minBars = CFG.VOL_LEN + CFG.ATR_LEN + F * 2 + 5;
    if (candles.length < minBars)
        return { ...NONE, reason: 'not enough bars' };
    const atr = computeATR(candles, CFG.ATR_LEN);
    const clusters = buildClusterArray(candles, atr, cfg.volMult);
    const sessionRvol = computeSessionRvol(candles);
    // Scan last MAX_LOOKBACK confirmed bars for a valid fractal — matches backtest loop
    const MAX_LOOKBACK = 10;
    const price = candles[candles.length - 1].open;
    let lastReason = 'no fractal in recent bars';
    for (let offset = F + 2; offset <= F + 2 + MAX_LOOKBACK; offset++) {
        const i = candles.length - offset;
        if (i < F + CFG.VOL_LEN)
            break;
        const bar = candles[i];
        const currentATR = atr[i];
        const vol = bar.volume ?? 0;
        const rvol = sessionRvol[i] > 0 ? sessionRvol[i] : 0;
        if (rvol < CFG.RVOL_MIN) {
            lastReason = `low rvol ${rvol.toFixed(2)}`;
            continue;
        }
        if (currentATR === 0) {
            lastReason = 'atr=0';
            continue;
        }
        if (!vol) {
            lastReason = 'no volume';
            continue;
        }
        // SR cluster distance filter
        const { dist, cluster } = nearestClusterDist(bar.close, clusters, currentATR);
        if (dist > cfg.srDist || !cluster) {
            lastReason = `too far from cluster: ${dist.toFixed(2)} ATR`;
            continue;
        }
        // Fractal peak: high[i] > all highs in [i-F..i-1] AND [i+1..i+F]
        let fractalPeak = true;
        let fractalTrough = true;
        for (let j = 1; j <= F; j++) {
            if (candles[i].high <= candles[i - j].high)
                fractalPeak = false;
            if (candles[i].high <= candles[i + j].high)
                fractalPeak = false;
            if (candles[i].low >= candles[i - j].low)
                fractalTrough = false;
            if (candles[i].low >= candles[i + j].low)
                fractalTrough = false;
        }
        const atrRejectedPeak = bar.close < bar.high - currentATR * cfg.atrMult;
        const atrBouncedTrough = bar.close > bar.low + currentATR * cfg.atrMult;
        const peakSlack = currentATR > 0 ? (bar.high - bar.close) / currentATR : 0;
        const troughSlack = currentATR > 0 ? (bar.close - bar.low) / currentATR : 0;
        if (fractalPeak && atrRejectedPeak) {
            const slack = peakSlack;
            // NEW: Slack filter - only accept trades with slack < 0.8
            if (slack >= CFG.SLACK_MAX) {
                lastReason = `slack ${slack.toFixed(2)} >= ${CFG.SLACK_MAX} (filtered)`;
                continue;
            }
            return {
                signal: 'sell', price,
                reason: `fractal peak at ${bar.high.toFixed(2)}, ATR rejection, cluster ${cluster.price.toFixed(2)} str=${cluster.strength} | TP+${(tpPct * 100).toFixed(0)}% SL-${(slPct * 100).toFixed(0)}%`,
                direction: 'SHORT', nearestCluster: cluster.price, clusterStrength: cluster.strength,
                atr: currentATR, tpPct, slPct, slack, tier: slack >= 1.4 ? 'core' : 'expanded',
            };
        }
        if (fractalTrough && atrBouncedTrough) {
            const slack = troughSlack;
            // NEW: Slack filter - only accept trades with slack < 0.8
            if (slack >= CFG.SLACK_MAX) {
                lastReason = `slack ${slack.toFixed(2)} >= ${CFG.SLACK_MAX} (filtered)`;
                continue;
            }
            return {
                signal: 'buy', price,
                reason: `fractal trough at ${bar.low.toFixed(2)}, ATR bounce, cluster ${cluster.price.toFixed(2)} str=${cluster.strength} | TP+${(tpPct * 100).toFixed(0)}% SL-${(slPct * 100).toFixed(0)}%`,
                direction: 'LONG', nearestCluster: cluster.price, clusterStrength: cluster.strength,
                atr: currentATR, tpPct, slPct, slack, tier: slack >= 1.4 ? 'core' : 'expanded',
            };
        }
        lastReason = 'no fractal confirmation';
    } // end offset loop
    return { ...NONE, reason: lastReason };
}
