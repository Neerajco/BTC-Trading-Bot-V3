import os
import time
import ccxt
import pandas as pd
from dotenv import load_dotenv
from notifier import send_telegram

# Import Our SMC Logic Engines
from smc_logic import detect_fvg
from mtf_scanner import get_latest_fvg
from execution import detect_liquidity_sweep

print("🚀 INITIATING SMC MASTER BOT V4.8 (GEOMETRY FILTER & DYNAMIC RR)...")

# --- 1. CONFIGURATION & CREDENTIALS ---
load_dotenv()
API_KEY = os.environ.get('BINANCE_API_KEY')
SECRET_KEY = os.environ.get('BINANCE_SECRET_KEY')

SYMBOL = 'BTC/USDT'
HTF = '4h'
LTF = '15m'
RISK_PERCENT = 0.01  # 🎯 1.0% Risk per trade
MIN_RR = 2.0         # 🎯 Minimum allowed RR (Geometry Filter)
MAX_RR = 7.0         # 🎯 Maximum allowed RR (Safety Cap)

# --- 2. EXCHANGE SETUP ---
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
    }
})
exchange.enable_demo_trading(True)  


# --- 3. HELPER FUNCTIONS ---
def get_market_data(symbol, timeframe, limit=100):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].apply(pd.to_numeric)
        return df
    except Exception as e:
        print(f"❌ API Fetch Error: {e}")
        return None

def check_open_positions(symbol):
    """Returns the current position amount. Bypasses CCXT Symbol formatting bug."""
    try:
        positions = exchange.fetch_positions()
        raw_symbol = symbol.replace('/', '') 
        for pos in positions:
            if pos['info'].get('symbol') == raw_symbol:
                return float(pos['contracts'])
        return 0.0
    except Exception as e:
        print(f"⚠️ API Error - Could not check position: {e}")
        return None # 🛡️ FAILSAFE

def place_smc_order(symbol, side, amount, entry_price, sl_price, tp_price, applied_rr):
    """Places a Market Order with Dynamic RR & Naked Position Failsafe."""
    close_side = 'sell' if side == 'buy' else 'buy'
    
    print(f"⚙️ EXECUTING {side.upper()} | Entry: {entry_price} | SL: {sl_price} | TP: {tp_price:.2f} | Size: {amount} BTC | RR: 1:{applied_rr:.2f}")

    try:
        # 1. Open Position
        exchange.create_market_order(symbol, side, amount)
    except Exception as e:
        print(f"❌ Entry Order Execution Failed: {e}")
        return False

    try:
        # 2. Place Strict Stop-Loss (workingType: CONTRACT_PRICE prevents -2021 Error)
        exchange.create_order(symbol, 'STOP_MARKET', close_side, amount, None, params={
            'stopPrice': float(sl_price),
            'reduceOnly': True,
            'workingType': 'CONTRACT_PRICE'
        })

        # 3. Place Dynamic Take-Profit 
        exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', close_side, amount, None, params={
            'stopPrice': float(tp_price),
            'reduceOnly': True,
            'workingType': 'CONTRACT_PRICE'
        })

        print("✅ SMC ORDER & DYNAMIC RISK MANAGEMENT DEPLOYED SUCCESSFULLY!")
        msg = f"🚨 SMART MONEY ENGAGED (1:{applied_rr:.2f} RR)!\nSymbol: {symbol}\nSide: {side.upper()}\nSize: {amount} BTC\nEntry: {entry_price}\nSL: {sl_price}\nTP: {tp_price:.2f}"
        send_telegram(msg)
        return True

    except Exception as e:
        print(f"❌ SL/TP Order Failed: {e}")
        print("🛡️ EMERGENCY FAILSAFE: Closing naked position to protect capital!")
        try:
            exchange.create_market_order(symbol, close_side, amount, params={'reduceOnly': True})
            exchange.cancel_all_orders(symbol)
            print("✅ Naked position safely closed.")
        except Exception as abort_err:
            print(f"🚨 CRITICAL ERROR: Could not close naked position! {abort_err}")
        return False


# --- 4. THE MASTER LOOP ---
def run_bot():
    print(f"\n📡 Scanning Market: {SYMBOL} | Waiting for Institutional Traps...")
    last_executed_candle = None  # 🛡️ Tracks the candle we last traded on

    while True:
        try:
            pos_amt = check_open_positions(SYMBOL)

            if pos_amt is None:
                print("⏳ API Error: Could not verify positions. Skipping cycle to prevent duplicate orders.")
                time.sleep(60)
                continue

            if pos_amt != 0:
                print(f"⏳ In Active Position ({pos_amt} {SYMBOL}). Waiting for SL or TP to hit...")
                time.sleep(60)
                continue
            else:
                try:
                    exchange.cancel_all_orders(SYMBOL)
                except Exception:
                    pass

            htf_df = get_market_data(SYMBOL, HTF, limit=100)
            ltf_df = get_market_data(SYMBOL, LTF, limit=100) 

            if htf_df is None or ltf_df is None:
                time.sleep(10)
                continue

            htf_fvg_df = detect_fvg(htf_df)
            active_fvg = get_latest_fvg(htf_fvg_df)

            if not active_fvg:
                print(f"[{time.strftime('%H:%M:%S')}] 📉 No HTF Institutional FVG found. Resting...")
                time.sleep(60)
                continue

            current_price = ltf_df['Close'].iloc[-1]
            current_candle_time = ltf_df['Timestamp'].iloc[-1]
            fvg_top, fvg_bot, fvg_type = active_fvg['top'], active_fvg['bot'], active_fvg['type']

            is_trigger, trigger_msg = detect_liquidity_sweep(ltf_df, fvg_top, fvg_bot, fvg_type)

            print(f"[{time.strftime('%H:%M:%S')}] Price: {current_price} | Zone: {fvg_top}-{fvg_bot} | Status: {trigger_msg}")

            # 🛡️ THE RE-ENTRY LOCK: Prevent machine-gunning orders on a single volatile candle
            if is_trigger and current_candle_time == last_executed_candle:
                print("⏳ Trap already traded in this 15m candle. Waiting for next candle to prevent over-trading...")
                time.sleep(60)
                continue

            if is_trigger:
                sweep_price = float(trigger_msg.split('Swept ')[1].split(',')[0])
                current_candle = ltf_df.iloc[-1]
                
                # --- THE GEOMETRIC DYNAMIC RR ENGINE ---
                lookback = 40
                skip_trade = False
                
                try:
                    if fvg_type == 'BULLISH':
                        sl_price = sweep_price - 10.0
                        risk_per_coin = current_price - sl_price
                        if risk_per_coin <= 0: continue

                        c_price = current_candle['Low']
                        recent_chunk = ltf_df.iloc[-lookback:-1]
                        b_price = recent_chunk['High'].max()
                        b_idx = recent_chunk['High'].idxmax()
                        b_pos = ltf_df.index.get_loc(b_idx)
                        origin_chunk = ltf_df.iloc[max(0, b_pos - lookback):b_pos]
                        a_price = origin_chunk['Low'].min()
                        
                        geo_target = (b_price * c_price) / a_price
                        raw_rr = (geo_target - current_price) / risk_per_coin

                    elif fvg_type == 'BEARISH':
                        sl_price = sweep_price + 10.0
                        risk_per_coin = sl_price - current_price
                        if risk_per_coin <= 0: continue

                        c_price = current_candle['High']
                        recent_chunk = ltf_df.iloc[-lookback:-1]
                        b_price = recent_chunk['Low'].min()
                        b_idx = recent_chunk['Low'].idxmin()
                        b_pos = ltf_df.index.get_loc(b_idx)
                        origin_chunk = ltf_df.iloc[max(0, b_pos - lookback):b_pos]
                        a_price = origin_chunk['High'].max()
                        
                        geo_target = (b_price * c_price) / a_price
                        raw_rr = (current_price - geo_target) / risk_per_coin
                        
                    # 🛡️ THE GEOMETRY FILTER
                    if raw_rr < MIN_RR:
                        print(f"🛡️ GEOMETRY FILTER: Weak momentum predicted (1:{raw_rr:.2f} RR). Skipping Trade.")
                        skip_trade = True

                except Exception as e:
                    print(f"⚠️ Geometry Math Error: {e}. Skipping to be safe.")
                    skip_trade = True

                if skip_trade:
                    time.sleep(60)
                    continue 

                # 🛡️ THE CLAMP: Lock RR between MIN_RR and MAX_RR
                applied_rr = min(raw_rr, MAX_RR)
                
                # Calculate exact Take Profit based on the clamped RR
                if fvg_type == 'BULLISH':
                    tp_price = current_price + (risk_per_coin * applied_rr)
                else:
                    tp_price = current_price - (risk_per_coin * applied_rr)

                print("\n" + "=" * 50)
                print("🚨 TRAP CONFIRMED & GEOMETRY ALIGNED! SMART MONEY ENGAGED! 🚨")

                # --- DYNAMIC RISK SIZING (1.0% RISK) ---
                try:
                    balance_data = exchange.fetch_balance()
                    usdt_balance = float(balance_data['total']['USDT'])
                except Exception as e:
                    print(f"⚠️ Could not fetch balance, defaulting to safety limit: {e}")
                    usdt_balance = 1000.0

                risk_amount = usdt_balance * RISK_PERCENT  

                if risk_per_coin > 0:
                    calculated_size = risk_amount / risk_per_coin
                    max_size = (usdt_balance * 19) / current_price # 19x leverage safety cap
                    trade_size = round(min(calculated_size, max_size), 3)
                else:
                    trade_size = 0.01

                if trade_size < 0.001:
                    trade_size = 0.001  
                # ---------------------------------------

                side = 'buy' if fvg_type == 'BULLISH' else 'sell'
                
                # Execute order
                success = place_smc_order(SYMBOL, side, trade_size, current_price, sl_price, tp_price, applied_rr)
                
                # 🛡️ Lock the candle so we don't double-trade it!
                if success:
                    last_executed_candle = current_candle_time

                print("=" * 50 + "\n")

            time.sleep(60)

        except Exception as e:
            print(f"❌ Main Loop Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()
