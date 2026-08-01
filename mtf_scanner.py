import ccxt
import pandas as pd
from smc_logic import detect_fvg, detect_swing_points
import time

# --- 1. INITIALIZE BINANCE DEMO ---
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
    }
})
exchange.enable_demo_trading(True)

# --- 2. SCANNER SETTINGS ---
SYMBOL = 'BTC/USDT'
HTF = '4h'
LTF = '15m'

def get_market_data(symbol, timeframe, limit=100):
    """Fetches Live OHLCV Data from Binance and returns a DataFrame"""
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        # SMC logic requires 'High', 'Low', 'Close' to be strictly numeric
        df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].apply(pd.to_numeric)
        return df
    except Exception as e:
        print(f"❌ Error fetching {timeframe} data: {e}")
        return None

def get_latest_fvg(df):
    """Scans the DataFrame backwards to find the most recent active FVG"""
    # Hum piche se (latest candles se) scan kar rahe hain
    for i in range(len(df)-1, -1, -1):
        if df['Bullish_FVG'].iloc[i]:
            return {'type': 'BULLISH', 'top': df['Bullish_FVG_Top'].iloc[i], 'bot': df['Bullish_FVG_Bot'].iloc[i]}
        elif df['Bearish_FVG'].iloc[i]:
            return {'type': 'BEARISH', 'top': df['Bearish_FVG_Top'].iloc[i], 'bot': df['Bearish_FVG_Bot'].iloc[i]}
    return None

def run_mtf_scanner():
    print(f"\n📡 Initiating MTF Institutional Scanner for {SYMBOL}...")
    print(f"HTF: {HTF} (Zone Detection) | LTF: {LTF} (Price Tracking)\n")
    
    # STEP 1: Fetch HTF Data & Apply SMC Math
    htf_df = get_market_data(SYMBOL, HTF, limit=100)
    if htf_df is None: return
    
    htf_fvg_df = detect_fvg(htf_df)
    active_fvg = get_latest_fvg(htf_fvg_df)
    
    # STEP 2: Fetch LTF Data for Current Live Price
    ltf_df = get_market_data(SYMBOL, LTF, limit=5)
    if ltf_df is None: return
    
    current_price = ltf_df['Close'].iloc[-1]
    
    print(f"💰 Live Price: {current_price}")
    print("-" * 50)
    
    # STEP 3: The Cross-Timeframe Logic (Where is Price vs The Zone?)
    if active_fvg:
        fvg_type = active_fvg['type']
        fvg_top = active_fvg['top']
        fvg_bot = active_fvg['bot']
        
        print(f"🎯 Latest 4H {fvg_type} FVG Found! [ Top: {fvg_top} | Bot: {fvg_bot} ]")
        
        if fvg_bot <= current_price <= fvg_top:
            print("🚨 TRAP ALERT: Price is currently INSIDE the Institutional FVG Zone!")
            print("⏳ Bot is on High Alert to look for 15m Liquidity Sweeps (Turtle Soup)...")
            
        elif fvg_type == 'BULLISH' and current_price > fvg_top:
            print("⏳ Price is ABOVE the Bullish FVG. Waiting for a drop (pullback) into the zone...")
            
        elif fvg_type == 'BEARISH' and current_price < fvg_bot:
            print("⏳ Price is BELOW the Bearish FVG. Waiting for a pump into the zone...")
            
        else:
            print("⚠️ Price has completely smashed through the FVG (Invalidated).")
    else:
        print("📉 No recent Fair Value Gaps found in the last 100 candles.")
    
    print("-" * 50)

if __name__ == "__main__":
    run_mtf_scanner()