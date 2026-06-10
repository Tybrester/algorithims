import csv
import io

csv_data = '''Symbol,Type,Strike,Expiration,Contracts,Premium,PnL,%PnL,Status,Entry Price,Exit Price,Created At,Closed At
"AVGO","call",470,"2026-06-02",1,1.948309623341899,2.322655839411425,,"closed",1.948309623341899,1.9715361817360133,"2026-06-01T19:55:13.016+00:00","2026-06-01T19:59:15.897+00:00"
"LLY","put",1075,"2026-06-02",1,4.819947627553859,-131.58790509870641,,"closed",4.819947627553859,3.5040685765667945,"2026-06-01T19:52:11.305+00:00","2026-06-01T19:59:15.897+00:00"
"AVGO","call",465,"2026-06-02",1,1.5725719239955396,78.62859619977698,,"closed",1.5725719239955396,3.17764742436097,"2026-06-01T19:52:09.105+00:00","2026-06-01T19:53:15.471+00:00"
"MSFT","call",460,"2026-06-02",1,4.2310753680688435,20.828435291224423,,"closed",4.2310753680688435,4.439359720981088,"2026-06-01T19:43:31.494+00:00","2026-06-01T19:59:45.797+00:00"
"AAPL","put",310,"2026-06-02",1,3.228222593127157,102.45935392013621,,"closed",3.228222593127157,4.252816132328519,"2026-06-01T19:37:04.014+00:00","2026-06-01T19:59:45.797+00:00"
"AMZN","put",260,"2026-06-02",2,1.080910800611207,83.69853111584291,,"closed",1.080910800611207,1.4994034561904215,"2026-06-01T19:36:13.012+00:00","2026-06-01T19:59:45.797+00:00"
"MSFT","call",465,"2026-06-02",1,4.026324804418067,-60.39,,"closed",4.026324804418067,3.3443573867799614,"2026-06-01T19:36:12.067+00:00","2026-06-01T19:42:56.811+00:00"
"META","put",600,"2026-06-02",1,3.8315491491086107,140.09568341152487,,"closed",3.8315491491086107,5.232505983223859,"2026-06-01T19:36:11.188+00:00","2026-06-01T19:59:15.897+00:00"
"NVDA","put",225,"2026-06-02",1,3.0013110790261806,40.14538480484049,,"closed",3.0013110790261806,3.4027649270745854,"2026-06-01T19:34:07.94+00:00","2026-06-01T19:59:45.797+00:00"
"META","put",605,"2026-06-02",1,3.0441052379228495,152.21,,"closed",3.0441052379228495,5.944304651243897,"2026-06-01T19:33:29.353+00:00","2026-06-01T19:35:25.926+00:00"'''

def analyze_trades(csv_content):
    reader = csv.DictReader(io.StringIO(csv_content))
    
    total_pnl = 0
    winning_trades = 0
    losing_trades = 0
    total_trades = 0
    symbol_stats = {}
    
    for row in reader:
        pnl = float(row['PnL'])
        symbol = row['Symbol']
        trade_type = row['Type']
        contracts = int(row['Contracts'])
        
        total_trades += 1
        total_pnl += pnl
        
        if pnl > 0:
            winning_trades += 1
        else:
            losing_trades += 1
        
        if symbol not in symbol_stats:
            symbol_stats[symbol] = {'trades': 0, 'pnl': 0, 'wins': 0, 'losses': 0}
        symbol_stats[symbol]['trades'] += 1
        symbol_stats[symbol]['pnl'] += pnl
        if pnl > 0:
            symbol_stats[symbol]['wins'] += 1
        else:
            symbol_stats[symbol]['losses'] += 1
    
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    return {
        'total_trades': total_trades,
        'total_pnl': total_pnl,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'symbol_stats': symbol_stats
    }

# Read full CSV
full_csv = open('c:/Users/tybre/Desktop/aivibe/Boof_23_50_15_5m_trades_2026-06-01.csv', 'r').read()
results = analyze_trades(full_csv)

print("=" * 60)
print("TRADE ANALYSIS: Boof 23/50/15 5m Strategy")
print("=" * 60)
print(f"\nTotal Trades: {results['total_trades']}")
print(f"Total P&L: ${results['total_pnl']:.2f}")
print(f"Winning Trades: {results['winning_trades']}")
print(f"Losing Trades: {results['losing_trades']}")
print(f"Win Rate: {results['win_rate']:.1f}%")

print("\n" + "-" * 40)
print("P&L BY SYMBOL")
print("-" * 40)
for symbol, stats in sorted(results['symbol_stats'].items(), key=lambda x: x[1]['pnl'], reverse=True):
    print(f"{symbol:6}: ${stats['pnl']:>10.2f} | {stats['wins']}/{stats['trades']} wins ({stats['wins']/stats['trades']*100:.0f}%)")
