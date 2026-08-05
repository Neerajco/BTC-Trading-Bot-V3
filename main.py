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

print("🚀 INITIATING SMC MASTER BOT V4 (FAILSAFE EDITION)...")

# --- 1. CONFIGURATION & CREDENTIALS ---
load_dotenv()
API_KEY = os.environ.get('BINANCE_API_KEY')
SECRET_KEY = os.environ.get('BINANCE_SECRET_KEY')

SYMBOL = 'BTC/USDT'
HTF = '4h'
LTF = '15m'
RISK_PERCENT = 0.01  # 🎯 1.0% Risk per trade
RR_RATIO = 7.0       # 🎯 1:7 Risk-to-Reward Ratio

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
exchange.enable_demo_trading(True)  # Live Demo Environment


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
    """Returns the current position amount. Returns None if API fails."""
    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            if pos['symbol'] == symbol:
                return float(pos['contracts'])
        return 0.0
    except Exception as e:
        print(f"⚠️ API Error - Could not check position: {e}")
        return None # 🛡️ FAILSAFE: Return None instead of 0.0 to prevent Amnesia Bug


def place_smc_order(symbol, side, amount, entry_price, sweep_price):
    """Places a Market Order with 1:7 Risk-Reward."""
    try:
        # Calculate Strict SMC Stop Loss & Take Profit (1:7 RR)
        if side == 'buy':
            sl_price = sweep_price - 10.0  # $10 buffer below sweep wick
            risk = entry_price - sl_price
            tp_price = entry_price + (risk * RR_RATIO)  # 🎯 1:7 Risk/Reward Target
            close_side = 'sell'
        else:
            sl_price = sweep_price + 10.0  # $10 buffer above sweep wick
            risk = sl_price - entry_price
            tp_price = entry_price - (risk * RR_RATIO)  # 🎯 1:7 Risk/Reward Target
            close_side = 'buy'

        print(f"⚙️ EXECUTING {side.upper()} | Entry: {entry_price} | SL: {sl_price} | TP: {tp_price} | Size: {amount} BTC")

        # 1. Open Position
        exchange.create_market_order(symbol, side, amount)

        # 2. Place Strict Stop-Loss (Reduce Only)
        exchange.create_order(symbol, 'STOP_MARKET', close_side, amount, None, params={
            'stopPrice': float(sl_price),
            'reduceOnly': True
        })

        # 3. Place Strict Take-Profit (Reduce Only)
        exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', close_side, amount, None, params={
            'stopPrice': float(tp_price),
            'reduceOnly': True
        })

        print("✅ SMC ORDER & RISK MANAGEMENT DEPLOYED SUCCESSFULLY!")
        msg = f"🚨 SMART MONEY ENGAGED (1:7 RR)!\nSymbol: {symbol}\nSide: {side.upper()}\nSize: {amount} BTC\nEntry: {entry_price}\nSL: {sl_price}\nTP: {tp_price}"
        send_telegram(msg)
        return True
    except Exception as e:
        print(f"❌ Order Execution Failed: {e}")
        return False


# --- 4. THE MASTER LOOP ---
def run_bot():
    print(f"\n📡 Scanning Market: {SYMBOL} | Waiting for Institutional Traps...")

    while True:
        try:
            # Step 1: Check if we are already in a trade
            pos_amt = check_open_positions(SYMBOL)

            # 🛡️ FAILSAFE: Pause if API crashes
            if pos_amt is None:
                print("⏳ API Error: Could not verify positions. Skipping cycle to prevent duplicate orders.")
                time.sleep(60)
                continue

            if pos_amt != 0:
                print(f"⏳ In Active Position ({pos_amt} {SYMBOL}). Waiting for SL or TP to hit...")
                time.sleep(60)
                continue
            else:
                # 🧹 AUTO-CLEANUP: Cancel all leftover orphaned SL/TP orders when position is flat!
                try:
                    exchange.cancel_all_orders(SYMBOL)
                except Exception:
                    pass

            # Step 2: Fetch Data
            htf_df = get_market_data(SYMBOL, HTF, limit=100)
            ltf_df = get_market_data(SYMBOL, LTF, limit=10)

            if htf_df is None or ltf_df is None:
                time.sleep(10)
                continue

            # Step 3: Identify the Institutional Setup (4H)
            htf_fvg_df = detect_fvg(htf_df)
            active_fvg = get_latest_fvg(htf_fvg_df)

            if not active_fvg:
                print("📉 No HTF Institutional FVG found. Resting...")
                time.sleep(60)
                continue

            # Step 4: Look for the Trap (15m Turtle Soup)
            current_price = ltf_df['Close'].iloc[-1]
            fvg_top, fvg_bot, fvg_type = active_fvg['top'], active_fvg['bot'], active_fvg['type']

            is_trigger, trigger_msg = detect_liquidity_sweep(ltf_df, fvg_top, fvg_bot, fvg_type)

            print(f"[{time.strftime('%H:%M:%S')}] Price: {current_price} | Zone: {fvg_top}-{fvg_bot} | Status: {trigger_msg}")

            # Step 5: EXECUTE KILL-SHOT WITH DYNAMIC RISK SIZING
            if is_trigger:
                print("\n" + "=" * 50)
                print("🚨 TRAP CONFIRMED. SMART MONEY ENGAGED! 🚨")

                sweep_price = float(trigger_msg.split('Swept ')[1].split(',')[0])

                # --- DYNAMIC RISK SIZING (1.0% RISK) ---
                try:
                    balance_data = exchange.fetch_balance()
                    usdt_balance = float(balance_data['total']['USDT'])
                except Exception as e:
                    print(f"⚠️ Could not fetch balance, defaulting to safety limit: {e}")
                    usdt_balance = 1000.0

                risk_amount = usdt_balance * RISK_PERCENT  # Risk 1.0% of balance

                if fvg_type == 'BULLISH':
                    risk_per_coin = abs(current_price - (sweep_price - 10.0))
                else:
                    risk_per_coin = abs((sweep_price + 10.0) - current_price)

                if risk_per_coin > 0:
                    calculated_size = risk_amount / risk_per_coin
                    # Safety cap for leverage limits (Max 19x leverage on demo)
                    max_size = (usdt_balance * 19) / current_price
                    trade_size = round(min(calculated_size, max_size), 3)
                else:
                    trade_size = 0.01

                if trade_size < 0.001:
                    trade_size = 0.001  # Minimum lot size threshold for BTC Futures
                # ---------------------------------------

                if fvg_type == 'BULLISH':
                    place_smc_order(SYMBOL, 'buy', trade_size, current_price, sweep_price)
                elif fvg_type == 'BEARISH':
                    place_smc_order(SYMBOL, 'sell', trade_size, current_price, sweep_price)

                print("=" * 50 + "\n")

            # Polling frequency: Check every 1 minute
            time.sleep(60)

        except Exception as e:
            print(f"❌ Main Loop Error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    run_bot()
