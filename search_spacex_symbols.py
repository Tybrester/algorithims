#!/usr/bin/env python3
"""
Search for SpaceX symbols on Alpaca
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest

# Live Alpaca credentials
LIVE_KEY = "AKHOSMJ7LAMPAWA2XFSL5W5TEL"
LIVE_SECRET = "GaHTUq3Yjh5MPp8c7yeB49gR5rAYWp9cXbvZ15GjCjxd"

def search_spacex_symbols():
    """Search for SpaceX-related symbols"""
    try:
        # Initialize live trading client
        trading_client = TradingClient(LIVE_KEY, LIVE_SECRET, paper=False)
        
        # Search for assets
        search_params = GetAssetsRequest()
        assets = trading_client.get_all_assets(search_params)
        
        # Look for SpaceX-related symbols
        spacex_symbols = []
        
        for asset in assets:
            symbol = asset.symbol
            name = asset.name.lower() if asset.name else ""
            
            # Search for SpaceX in symbol or name
            if "spacex" in name or "space" in name:
                spacex_symbols.append({
                    'symbol': symbol,
                    'name': asset.name,
                    'status': asset.status,
                    'exchange': asset.exchange,
                    'tradable': asset.tradable
                })
        
        print("SpaceX-related symbols found:")
        print("=" * 80)
        
        if spacex_symbols:
            for sym in spacex_symbols:
                print(f"Symbol: {sym['symbol']}")
                print(f"Name: {sym['name']}")
                print(f"Status: {sym['status']}")
                print(f"Exchange: {sym['exchange']}")
                print(f"Tradable: {sym['tradable']}")
                print("-" * 40)
        else:
            print("No SpaceX symbols found")
            print("Searching for other space-related symbols...")
            
            # Look for other space-related companies
            space_symbols = []
            for asset in assets:
                symbol = asset.symbol
                name = asset.name.lower() if asset.name else ""
                
                if any(keyword in name for keyword in ["space", "rocket", "aerospace", "satellite"]):
                    if asset.status.value == "active" and asset.tradable:
                        space_symbols.append({
                            'symbol': symbol,
                            'name': asset.name,
                            'status': asset.status,
                            'exchange': asset.exchange,
                            'tradable': asset.tradable
                        })
            
            if space_symbols:
                print("Other space-related active symbols:")
                for sym in space_symbols[:10]:  # Show first 10
                    print(f"{sym['symbol']}: {sym['name']}")
        
        return spacex_symbols
        
    except Exception as e:
        print(f"❌ Error searching symbols: {e}")
        return []

if __name__ == "__main__":
    print("Searching for SpaceX symbols on Alpaca LIVE")
    print("=" * 50)
    
    symbols = search_spacex_symbols()
