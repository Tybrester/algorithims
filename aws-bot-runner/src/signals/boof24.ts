// =========================================================
// BOOF 24.0 — Boof 23 Signal + 5m ZigZag Trend Gate
// Core signal: IDENTICAL to Boof 23 (SR cluster + fractal + ZigZag)
// Extra gate:  5m ZigZag trend must AGREE with the 1m signal direction
//   - LONG  signal only passes if 5m ZigZag trend == 'down' (bouncing off low)
//   - SHORT signal only passes if 5m ZigZag trend == 'up'   (fading high)
// Result: fewer trades, same or better WR — cuts counter-trend noise
// =========================================================

import { Candle, Boof23Result, getBoof23Signal } from './boof23';

// ─────────────────────────────────────────────
// BOOF24 SCAN LIST
// ─────────────────────────────────────────────
export const BOOFINGTON24 = ['NVDA', 'AAPL', 'META', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'TSLA', 'LLY', 'PLTR'] as const;

// ─────────────────────────────────────────────
// 5m ZigZag — built from 1m candles by aggregating every 5 bars
// ─────────────────────────────────────────────
interface ZZ5State {
  trend: 'up' | 'down' | '';
}

function build5mZigZag(candles1m: Candle[]): ZZ5State {
  // Aggregate 1m candles into 5m bars
  const bars5m: Candle[] = [];
  const step = 5;
  for (let i = 0; i + step <= candles1m.length; i += step) {
    const slice = candles1m.slice(i, i + step);
    bars5m.push({
      time:   slice[slice.length - 1].time,
      open:   slice[0].open,
      high:   Math.max(...slice.map(c => c.high)),
      low:    Math.min(...slice.map(c => c.low)),
      close:  slice[slice.length - 1].close,
      volume: slice.reduce((s, c) => s + (c.volume ?? 0), 0),
    });
  }

  if (bars5m.length < 3) return { trend: '' };

  let trend: 'up' | 'down' | '' = '';
  let lastHigh = bars5m[0].high;
  let lastLow  = bars5m[0].low;

  for (let i = 1; i < bars5m.length; i++) {
    const c = bars5m[i];
    if (c.close > lastHigh || c.open > lastHigh) {
      trend    = 'up';
      lastHigh = c.high;
      lastLow  = c.low;
    } else if (c.close < lastLow || c.open < lastLow) {
      trend    = 'down';
      lastHigh = c.high;
      lastLow  = c.low;
    }
  }

  return { trend };
}

// ─────────────────────────────────────────────
// MAIN SIGNAL FUNCTION
// ─────────────────────────────────────────────
export function getBoof24Signal(
  candles: Candle[],
  symbol = 'NVDA',
  tpPct = 0.35,
  slPct = 0.15
): Boof23Result {
  const base = getBoof23Signal(candles, symbol, tpPct, slPct);

  if (base.signal === 'none') return base;

  const zz5 = build5mZigZag(candles);

  // Gate: 5m trend must align with signal direction
  // LONG  (buy)  → 5m ZZ should be 'down'  (we're bouncing off a 5m low)
  // SHORT (sell) → 5m ZZ should be 'up'    (we're fading a 5m high)
  if (zz5.trend === '') {
    return { ...base, signal: 'none', reason: `B24: ${base.reason} | 5m ZZ not established` };
  }

  if (base.signal === 'buy' && zz5.trend !== 'down') {
    return { ...base, signal: 'none', reason: `B24: LONG blocked — 5m ZZ is '${zz5.trend}' (need 'down')` };
  }

  if (base.signal === 'sell' && zz5.trend !== 'up') {
    return { ...base, signal: 'none', reason: `B24: SHORT blocked — 5m ZZ is '${zz5.trend}' (need 'up')` };
  }

  return {
    ...base,
    reason: `B24: ${base.reason} | 5m ZZ=${zz5.trend} ✓`,
  };
}
