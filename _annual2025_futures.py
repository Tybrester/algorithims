import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21
import backtest_boof22 as bt22
import backtest_boof23 as bt23
import yfinance as yf
import pandas as pd

TRADE        = 200
TP_PCT       =  0.15   # +15% option TP
SL_PCT       = -0.50   # -50% option SL
STOCK_TP_PCT =  0.0015  # +0.15% underlying move
STOCK_SL_PCT = -0.005   # -0.5% underlying move

SYMBOLS = ['NQ=F', 'ES=F', 'CL=F', 'GC=F', 'RTY=F']

# yfinance 1h covers full year
months = [
    ('Jan 25', '2025-01-01', '2025-02-01', 23),
    ('Feb 25', '2025-02-01', '2025-03-01', 20),
    ('Mar 25', '2025-03-01', '2025-04-01', 21),
    ('Apr 25', '2025-04-01', '2025-05-01', 22),
    ('May 25', '2025-05-01', '2025-06-01', 21),
    ('Jun 25', '2025-06-01', '2025-07-01', 21),
    ('Jul 25', '2025-07-01', '2025-08-01', 23),
    ('Aug 25', '2025-08-01', '2025-09-01', 21),
    ('Sep 25', '2025-09-01', '2025-10-01', 22),
    ('Oct 25', '2025-10-01', '2025-11-01', 23),
    ('Nov 25', '2025-11-01', '2025-12-01', 20),
    ('Dec 25', '2025-12-01', '2026-01-01', 23),
]

def fetch_yf_bars(symbol, start, end, interval='1h'):
    try:
        df = yf.download(symbol, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
        if df is None or len(df) < 20:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        return df[['open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        print(f"  Error fetching {symbol}: {e}")
        return None

def run_bot(bot_name, run_fn):
    print()
    print('=' * 75)
    print(f'Boof {bot_name}  |  Jan-Dec 2025  |  5 Futures  |  +0.15% TP / -0.5% SL  |  1h bars')
    print('=' * 75)
    print('Month  Trades  /day   PF      PnL         Losing syms')
    print('-' * 75)

    results = []
    sym_totals = {s: 0 for s in SYMBOLS}

    for label, start, end, tdays in months:
        month_trades = month_tp = month_sl = month_tm = 0
        month_pnl = 0.0
        losing_syms = []

        for sym in SYMBOLS:
            df = fetch_yf_bars(sym, start, end)
            if df is None or len(df) < 20:
                continue

            trades = run_fn(df, sym)

            tp_ct = sum(1 for t in trades if t['exit_type'] == 'tp')
            sl_ct = sum(1 for t in trades if t['exit_type'] == 'sl')
            tm_ct = sum(1 for t in trades if t['exit_type'] == 'time')
            pnl   = tp_ct * TRADE * TP_PCT + sl_ct * TRADE * SL_PCT + tm_ct * TRADE * 0.02

            month_trades += len(trades)
            month_tp     += tp_ct
            month_sl     += sl_ct
            month_tm     += tm_ct
            month_pnl    += pnl
            sym_totals[sym] += pnl
            if pnl < 0:
                losing_syms.append(sym.replace('=F',''))

        gross_win  = month_tp * TRADE * TP_PCT
        gross_loss = max(month_sl * TRADE * abs(SL_PCT), 1)
        pf = round(gross_win / gross_loss, 2)
        ls_str = '  LOSING: ' + ', '.join(losing_syms) if losing_syms else ''
        print(label.ljust(7) + str(month_trades).rjust(6) + str(round(month_trades/tdays,1)).rjust(7) + str(pf).rjust(7) + ('  +' + str(round(month_pnl))).rjust(12) + ls_str)
        results.append((label, month_trades, tdays, pf, month_pnl, losing_syms))

    total = sum(p for _,_,_,_,p,_ in results)
    tdays_total = sum(d for _,_,d,_,_,_ in results)
    print('-' * 75)
    print('TOTAL' + ' '*35 + ('+' if total >= 0 else '') + str(round(total)))
    print('Avg/month  : ' + ('+' if total >= 0 else '') + str(round(total / len(results))))
    print('Avg/day    : ' + ('+' if total >= 0 else '') + str(round(total / tdays_total)))
    losing_months = sum(1 for _,_,_,_,p,_ in results if p < 0)
    print('Losing months: ' + str(losing_months) + '/' + str(len(results)))
    print()
    print('Per-symbol 2025 totals:')
    print('-' * 40)
    for sym, tot in sorted(sym_totals.items(), key=lambda x: -x[1]):
        sign = '+' if tot >= 0 else ''
        print('  ' + sym.replace('=F','').ljust(6) + sign + str(round(tot)))

# Override TP/SL module constants before running
bt21.TP_PCT = STOCK_TP_PCT
bt21.SL_PCT = STOCK_SL_PCT
bt22.TP_PCT = STOCK_TP_PCT  # note: boof22 also reads tp_pct/sl_pct as args
bt23.TP_PCT = STOCK_TP_PCT
bt23.SL_PCT = STOCK_SL_PCT

print('Fetching 5 futures x 12 months via yfinance 1h bars ...')
print()

run_bot('21.0', lambda df, sym: bt21.backtest(df, symbol=sym))
run_bot('22.0', lambda df, sym: bt22.run_boof22(df, symbol=sym, tp_pct=STOCK_TP_PCT, sl_pct=STOCK_SL_PCT))
run_bot('23.0', lambda df, sym: bt23.run_boof23(df, symbol=sym))
