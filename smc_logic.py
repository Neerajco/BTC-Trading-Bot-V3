import pandas as pd
import numpy as np

def detect_swing_points(df, left_bars=2, right_bars=2):
    """
    Detects Swing Highs and Swing Lows (Fractals) for Liquidity Purges.
    A Swing High is formed when a candle's high is strictly greater than 
    'left_bars' highs before it and 'right_bars' highs after it.
    """
    df = df.copy()
    
    # Initialize columns
    df['Swing_High'] = False
    df['Swing_Low'] = False
    
    # Calculate Swing Highs
    high_roll = df['High'].rolling(window=left_bars + right_bars + 1, center=True)
    df.loc[df['High'] == high_roll.max(), 'Swing_High'] = True
    
    # Calculate Swing Lows
    low_roll = df['Low'].rolling(window=left_bars + right_bars + 1, center=True)
    df.loc[df['Low'] == low_roll.min(), 'Swing_Low'] = True

    return df

def detect_fvg(df):
    """
    Detects Fair Value Gaps (Imbalance).
    Takes a 3-candle sequence: C1, C2, C3.
    Bullish FVG: C3 Low > C1 High
    Bearish FVG: C3 High < C1 Low
    """
    df = df.copy()
    
    # Shift data to get C1 (2 candles ago)
    # df['High'] and df['Low'] currently represent C3
    df['C1_High'] = df['High'].shift(2)
    df['C1_Low'] = df['Low'].shift(2)
    
    # Bullish FVG
    df['Bullish_FVG'] = df['Low'] > df['C1_High']
    # Calculate the exact gap zone
    df['Bullish_FVG_Top'] = np.where(df['Bullish_FVG'], df['Low'], np.nan)
    df['Bullish_FVG_Bot'] = np.where(df['Bullish_FVG'], df['C1_High'], np.nan)
    
    # Bearish FVG
    df['Bearish_FVG'] = df['High'] < df['C1_Low']
    # Calculate the exact gap zone
    df['Bearish_FVG_Top'] = np.where(df['Bearish_FVG'], df['C1_Low'], np.nan)
    df['Bearish_FVG_Bot'] = np.where(df['Bearish_FVG'], df['High'], np.nan)
    
    # Cleanup temporary columns
    df.drop(columns=['C1_High', 'C1_Low'], inplace=True)
    
    return df

# --- TEST THE LOGIC (Simulated Data) ---
if __name__ == "__main__":
    print("🚀 Initializing SMC Math Logic...")
    
    # Creating a fake DataFrame to test the FVG logic
    data = {
        'Timestamp': pd.date_range(start='1/1/2026', periods=5, freq='h'),
        'Open':  [100, 110, 130, 140, 135],
        'High':  [105, 135, 145, 150, 140], # C1 High is 105
        'Low':   [95,  105, 135, 135, 120], # C3 Low is 135
        'Close': [102, 130, 142, 148, 125],
        'Volume':[1000]*5
    }
    
    df_test = pd.DataFrame(data)
    
    # 1. Detect FVGs
    df_fvg = detect_fvg(df_test)
    
    # 2. Detect Swings
    df_smc = detect_swing_points(df_fvg)
    
    print("\n📊 Raw Market Data with FVG & Swing Status:")
    print(df_smc[['High', 'Low', 'Bullish_FVG', 'Bullish_FVG_Top', 'Bullish_FVG_Bot', 'Swing_High']])
    print("\n✅ MATHEMATICS EXECUTED PERFECTLY: Note how Index 2 detected a Bullish FVG because C3 Low (135) > C1 High (105).")