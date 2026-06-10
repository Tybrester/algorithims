/**
 * BOOF 24 — Stock Classification & Strategy Router
 * Two separate lists: 1m and 5m timeframes
 */

export type StockType = 'BREAKOUT_STOCK' | 'IMPULSE_STOCK' | 'SKIP';
export type Timeframe = '1m' | '5m';

// Stock config interface
export interface Boof24StockConfig {
  symbol: string;
  type: StockType;
  timeframe: Timeframe;
  baselineAvg: number;
  breakoutAvg: number;
  baselineWR: number;
  breakoutWR: number;
  maxTradesPerDay: number;
  reason: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// BOOF 24 1M — High volatility / event-driven stocks
// ═══════════════════════════════════════════════════════════════════════════════
export const BOOF24_1M_STOCKS: Record<string, Boof24StockConfig> = {
  PLTR: {
    symbol: 'PLTR',
    type: 'BREAKOUT_STOCK',
    timeframe: '1m',
    baselineAvg: 0.030,
    breakoutAvg: 0.067,
    baselineWR: 48.2,
    breakoutWR: 52.1,
    maxTradesPerDay: 3,
    reason: '1m breakout +0.037% edge — best 1m performer'
  },
  TSLA: {
    symbol: 'TSLA',
    type: 'BREAKOUT_STOCK',
    timeframe: '1m',
    baselineAvg: 0.017,
    breakoutAvg: 0.051,
    baselineWR: 48.6,
    breakoutWR: 51.4,
    maxTradesPerDay: 3,
    reason: '1m breakout +0.034% edge'
  },
  COIN: {
    symbol: 'COIN',
    type: 'BREAKOUT_STOCK',
    timeframe: '1m',
    baselineAvg: 0.057,
    breakoutAvg: 0.064,
    baselineWR: 49.6,
    breakoutWR: 48.9,
    maxTradesPerDay: 3,
    reason: '1m equal, slight breakout edge + more trades'
  },
  AMD: {
    symbol: 'AMD',
    type: 'IMPULSE_STOCK',
    timeframe: '1m',
    baselineAvg: 0.053,
    breakoutAvg: 0.043,
    baselineWR: 52.1,
    breakoutWR: 49.4,
    maxTradesPerDay: 2,
    reason: '1m baseline +0.010% edge, more trades'
  },
  BABA: {
    symbol: 'BABA',
    type: 'BREAKOUT_STOCK',
    timeframe: '1m',
    baselineAvg: 0.032,
    breakoutAvg: 0.043,
    baselineWR: 50.3,
    breakoutWR: 52.1,
    maxTradesPerDay: 3,
    reason: '1m breakout +0.011% edge'
  },
  TGT: {
    symbol: 'TGT',
    type: 'IMPULSE_STOCK',
    timeframe: '1m',
    baselineAvg: 0.055,
    breakoutAvg: 0.034,
    baselineWR: 53.2,
    breakoutWR: 53.5,
    maxTradesPerDay: 2,
    reason: '1m baseline +0.021% edge — selective use'
  },
  HD: {
    symbol: 'HD',
    type: 'IMPULSE_STOCK',
    timeframe: '1m',
    baselineAvg: 0.044,
    breakoutAvg: 0.019,
    baselineWR: 50.7,
    breakoutWR: 48.0,
    maxTradesPerDay: 2,
    reason: '1m baseline +0.025% edge — selective use'
  }
};

// ═══════════════════════════════════════════════════════════════════════════════
// BOOF 24 5M — Standard timeframe for index ETFs and large caps
// ═══════════════════════════════════════════════════════════════════════════════
export const BOOF24_5M_STOCKS: Record<string, Boof24StockConfig> = {
  SPY: {
    symbol: 'SPY',
    type: 'IMPULSE_STOCK',
    timeframe: '5m',
    baselineAvg: 0.009,
    breakoutAvg: -0.006,
    baselineWR: 47.4,
    breakoutWR: 35.0,
    maxTradesPerDay: 2,
    reason: '5m baseline only — SPY trades on impulse'
  },
  QQQ: {
    symbol: 'QQQ',
    type: 'IMPULSE_STOCK',
    timeframe: '5m',
    baselineAvg: 0.010,
    breakoutAvg: -0.006,
    baselineWR: 46.7,
    breakoutWR: 36.7,
    maxTradesPerDay: 2,
    reason: '5m baseline only — QQQ trades on impulse'
  },
  NFLX: {
    symbol: 'NFLX',
    type: 'IMPULSE_STOCK',
    timeframe: '5m',
    baselineAvg: 0.034,
    breakoutAvg: -0.006,
    baselineWR: 44.0,
    breakoutWR: 38.9,
    maxTradesPerDay: 2,
    reason: '5m baseline +0.040% edge — breakout kills it'
  },
  NVDA: {
    symbol: 'NVDA',
    type: 'BREAKOUT_STOCK',
    timeframe: '5m',
    baselineAvg: 0.001,
    breakoutAvg: 0.026,
    baselineWR: 40.1,
    breakoutWR: 41.6,
    maxTradesPerDay: 3,
    reason: '5m breakout +0.025% edge'
  },
  AAPL: {
    symbol: 'AAPL',
    type: 'IMPULSE_STOCK',
    timeframe: '5m',
    baselineAvg: 0.043,
    breakoutAvg: 0.029,
    baselineWR: 49.2,
    breakoutWR: 44.3,
    maxTradesPerDay: 2,
    reason: '5m baseline +0.014% edge — use breakout filter'
  },
  MSFT: {
    symbol: 'MSFT',
    type: 'SKIP',
    timeframe: '5m',
    baselineAvg: -0.064,
    breakoutAvg: -0.059,
    baselineWR: 34.7,
    breakoutWR: 36.5,
    maxTradesPerDay: 0,
    reason: '5m both configs negative — SKIP'
  }
};

// ═══════════════════════════════════════════════════════════════════════════════
// COMBINED STOCKS MAP (for lookup)
// ═══════════════════════════════════════════════════════════════════════════════
export const BOOF24_STOCKS: Record<string, Boof24StockConfig> = {
  ...BOOF24_1M_STOCKS,
  ...BOOF24_5M_STOCKS
};

// Dropdown lists for UI
export const BOOF24_1M_SYMBOL_LIST = ['PLTR', 'TSLA', 'COIN', 'AMD', 'BABA', 'TGT', 'HD'];
export const BOOF24_5M_SYMBOL_LIST = ['SPY', 'QQQ', 'NFLX', 'NVDA', 'AAPL', 'MSFT'];
export const BOOF24_ALL_SYMBOLS = [...BOOF24_1M_SYMBOL_LIST, ...BOOF24_5M_SYMBOL_LIST];

// Stock type accessors
export function getStockType(symbol: string): StockType {
  return BOOF24_STOCKS[symbol]?.type || 'SKIP';
}

export function getMaxTrades(symbol: string): number {
  return BOOF24_STOCKS[symbol]?.maxTradesPerDay || 0;
}

export function shouldUseBreakout(symbol: string): boolean {
  return BOOF24_STOCKS[symbol]?.type === 'BREAKOUT_STOCK';
}

// Strategy Router
export function boofRouter(
  symbol: string,
  signal: {
    breakoutCondition: boolean;
    baselineCondition: boolean;
    volZ: number;
    vwapAligned: boolean;
    direction: 'long' | 'short';
  },
  tradesToday: number
): { action: 'TRADE' | 'SKIP'; config: 'breakout' | 'baseline' | null; reason: string } {
  
  const stock = BOOF24_STOCKS[symbol];
  
  if (!stock) {
    return { action: 'SKIP', config: null, reason: 'Symbol not in BOOF24 list' };
  }
  
  if (stock.type === 'SKIP') {
    return { action: 'SKIP', config: null, reason: 'Stock labeled SKIP — no edge' };
  }
  
  // Check daily trade limit
  if (tradesToday >= stock.maxTradesPerDay) {
    return { action: 'SKIP', config: null, reason: `Max ${stock.maxTradesPerDay} trades/day reached` };
  }
  
  // Route based on stock type
  if (stock.type === 'BREAKOUT_STOCK') {
    if (signal.breakoutCondition && signal.volZ >= 1.8 && signal.vwapAligned) {
      return { 
        action: 'TRADE', 
        config: 'breakout', 
        reason: `${symbol} BREAKOUT trade — Z>${signal.volZ.toFixed(1)}` 
      };
    }
    return { action: 'SKIP', config: null, reason: 'Breakout condition not met' };
  }
  
  if (stock.type === 'IMPULSE_STOCK') {
    if (signal.baselineCondition && signal.volZ >= 1.8 && signal.vwapAligned) {
      return { 
        action: 'TRADE', 
        config: 'baseline', 
        reason: `${symbol} IMPULSE trade — Z>${signal.volZ.toFixed(1)}` 
      };
    }
    return { action: 'SKIP', config: null, reason: 'Baseline condition not met' };
  }
  
  return { action: 'SKIP', config: null, reason: 'Unknown stock type' };
}

// Daily trade counter per stock
export class Boof24TradeTracker {
  private trades: Map<string, { date: string; count: number }> = new Map();
  
  canTrade(symbol: string): boolean {
    const stock = BOOF24_STOCKS[symbol];
    if (!stock || stock.type === 'SKIP') return false;
    
    const today = new Date().toISOString().split('T')[0];
    const record = this.trades.get(symbol);
    
    if (!record || record.date !== today) {
      return true; // Fresh day
    }
    
    return record.count < stock.maxTradesPerDay;
  }
  
  recordTrade(symbol: string): void {
    const today = new Date().toISOString().split('T')[0];
    const record = this.trades.get(symbol);
    
    if (!record || record.date !== today) {
      this.trades.set(symbol, { date: today, count: 1 });
    } else {
      record.count++;
    }
  }
  
  getRemaining(symbol: string): number {
    const stock = BOOF24_STOCKS[symbol];
    if (!stock) return 0;
    
    const today = new Date().toISOString().split('T')[0];
    const record = this.trades.get(symbol);
    
    if (!record || record.date !== today) {
      return stock.maxTradesPerDay;
    }
    
    return Math.max(0, stock.maxTradesPerDay - record.count);
  }
}

// Export summary for debugging
export function getBoof24Summary(): string {
  const m1 = Object.values(BOOF24_1M_STOCKS);
  const m5 = Object.values(BOOF24_5M_STOCKS);
  
  const m1Breakout = m1.filter(s => s.type === 'BREAKOUT_STOCK');
  const m1Impulse = m1.filter(s => s.type === 'IMPULSE_STOCK');
  const m5Breakout = m5.filter(s => s.type === 'BREAKOUT_STOCK');
  const m5Impulse = m5.filter(s => s.type === 'IMPULSE_STOCK');
  const skip = m5.filter(s => s.type === 'SKIP');
  
  return `
╔════════════════════════════════════════════════════════════════════════════╗
║                    BOOF 24 STOCK CLASSIFICATION                            ║
╠════════════════════════════════════════════════════════════════════════════╣
║  BOOF 24 1M — High Volatility / Event-Driven (1-minute timeframe)         ║
╚════════════════════════════════════════════════════════════════════════════╝

BREAKOUT (3/day):  ${m1Breakout.map(s => s.symbol).join(', ')}
IMPULSE (2/day):   ${m1Impulse.map(s => s.symbol).join(', ')}

╔════════════════════════════════════════════════════════════════════════════╗
║  BOOF 24 5M — Index ETFs & Large Caps (5-minute timeframe)                 ║
╚════════════════════════════════════════════════════════════════════════════╝

BREAKOUT (3/day):  ${m5Breakout.map(s => s.symbol).join(', ')}
IMPULSE (2/day):   ${m5Impulse.map(s => s.symbol).join(', ')}
SKIP (0/day):      ${skip.map(s => s.symbol).join(', ')}

Total: ${BOOF24_ALL_SYMBOLS.length} stocks (7 in 1m list + 6 in 5m list)
`;
}

// Helper: Get timeframe for a symbol
export function getStockTimeframe(symbol: string): Timeframe | null {
  return BOOF24_STOCKS[symbol]?.timeframe || null;
}

// Helper: Get stocks by timeframe
export function getStocksByTimeframe(tf: Timeframe): string[] {
  return tf === '1m' ? BOOF24_1M_SYMBOL_LIST : BOOF24_5M_SYMBOL_LIST;
}
