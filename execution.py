import pandas as pd
import numpy as np
from smc_logic import detect_swing_points

def detect_liquidity_sweep(ltf_df, fvg_top, fvg_bot, fvg_type):
    """
    SMC Execution Engine: Detects the 'Turtle Soup' Trap.
    Matches the current 15m candle against previous swing points inside the FVG zone.
    """
    df = ltf_df.copy()
    
    # 1. Pehle 15m chart par chote Swing Highs/Lows mark karo
    df = detect_swing_points(df, left_bars=2, right_bars=2)
    
    # Last closed candle (The Trigger Candle)
    last_candle = df.iloc[-1]
    
    if fvg_type == 'BULLISH':
        # Pichle Swing Lows dhoondo
        swing_lows = df[df['Swing_Low'] == True]
        if len(swing_lows) == 0:
            return False, "WAITING: No Swing Lows found yet."
            
        recent_swing_low_price = swing_lows['Low'].iloc[-1]
        
        # --- THE TRAP MATH ---
        # 1. Kya price pichle low ke niche gaya? (Stop Loss Hunted)
        sweep_condition = last_candle['Low'] < recent_swing_low_price 
        # 2. Kya close wapas upar ho gaya? (Leaving a wick)
        close_inside = last_candle['Close'] > recent_swing_low_price
        # 3. Kya yeh sab hamare 4H FVG Zone ke andar hua?
        in_zone = last_candle['Low'] <= fvg_top
        
        if sweep_condition and close_inside and in_zone:
            msg = f"🔥 LONG TRIGGER: Turtle Soup! Swept {recent_swing_low_price}, Closed {last_candle['Close']}"
            return True, msg
            
    elif fvg_type == 'BEARISH':
        # Pichle Swing Highs dhoondo
        swing_highs = df[df['Swing_High'] == True]
        if len(swing_highs) == 0:
            return False, "WAITING: No Swing Highs found yet."
            
        recent_swing_high_price = swing_highs['High'].iloc[-1]
        
        # --- THE TRAP MATH ---
        # 1. Kya price pichle high ke upar gaya? (Stop Loss Hunted)
        sweep_condition = last_candle['High'] > recent_swing_high_price 
        # 2. Kya close wapas niche ho gaya? (Leaving a wick)
        close_inside = last_candle['Close'] < recent_swing_high_price
        # 3. Kya yeh sab hamare 4H FVG Zone ke andar hua?
        in_zone = last_candle['High'] >= fvg_bot
        
        if sweep_condition and close_inside and in_zone:
            msg = f"🩸 SHORT TRIGGER: Turtle Soup! Swept {recent_swing_high_price}, Closed {last_candle['Close']}"
            return True, msg
            
    return False, "⏸️ WAITING: Price in zone, but no Liquidity Sweep yet."

# --- TEST THE TRAP LOGIC ---
if __name__ == "__main__":
    print("🚀 Initiating Turtle Soup Execution Math...")
    
    # Fake 15m Data (Creating a deliberate Trap scenario)
    data = {
        'Timestamp': pd.date_range(start='1/1/2026', periods=6, freq='15min'),
        'Open':  [100, 110, 105, 108, 106, 103],
        'High':  [105, 115, 110, 112, 110, 108],
        'Low':   [95,  102, 105, 106, 105, 98],  # Index 1 is Swing Low (102). Last candle drops to 98!
        'Close': [102, 108, 107, 109, 107, 104], # Last candle closes at 104 (Back above 102!)
        'Volume':[100]*6
    }
    df_ltf = pd.DataFrame(data)
    
    # Assume Scanner Found this 4H Bullish FVG Zone
    fvg_top = 105
    fvg_bot = 90
    
    print(f"\n🎯 4H FVG Zone Active: {fvg_top} - {fvg_bot}")
    
    is_trigger, message = detect_liquidity_sweep(df_ltf, fvg_top, fvg_bot, 'BULLISH')
    
    print("\n📊 Output of Execution Engine:")
    print(message)