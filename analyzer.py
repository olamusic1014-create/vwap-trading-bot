import yfinance as yf
import pandas as pd
import datetime
import twstock
import numpy as np
import time
import random
import streamlit as st
from fugle_marketdata import RestClient 

# --- 熱門股池 (保持不變) ---
MARKET_POOL = [
    '2330', '2317', '2454', '2382', '2303', '2881', '2891', '2308', '3711', '3037',
    '3035', '3017', '2368', '3231', '3443', '3661', '6669', '2376', '2356', '2301',
    '2603', '2609', '2615', '2618', '2610', '2637', 
    '1513', '1519', '1503', '1504', '1609', 
    '3044', '2383', '6274', '6213', '2421', '3013', 
    '8046', '8069', '3533', '3529', '5269', '3653', 
    '2409', '3481', '6116', '2481', '3008', 
    '2363', '2344', '2449', '2313', '2324', 
    '3034', '4961', '4919', '2458', '3583', 
    '2353', '2323', '2352', '3260', '6239'
]

# --- 1. 海選部隊：使用 Yahoo ---
@st.cache_data(ttl=900)
def screen_hot_stocks(limit=15):
    screened_list = []
    print("正在掃描市場熱門股 (Yahoo)...")
    
    for symbol_raw in MARKET_POOL:
        symbol = f"{symbol_raw}.TW" 
        time.sleep(random.uniform(0.1, 0.25)) 
        
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="3mo", interval="1d")
            if len(hist) < 20: continue
            
            ma20 = hist['Close'].rolling(window=20).mean().iloc[-1]
            current_price = hist['Close'].iloc[-1]
            if current_price < ma20: continue
                
            hist['Range_Pct'] = ((hist['High'] - hist['Low']) / hist['Close']) * 100
            avg_volatility = hist['Range_Pct'].tail(10).mean()
            if avg_volatility >= 2.0:
                screened_list.append({'symbol': symbol, 'volatility': avg_volatility})
        except: continue
        
    screened_list.sort(key=lambda x: x['volatility'], reverse=True)
    return screened_list[:limit]

# --- 2. 特種部隊：富果 API ---
def get_fugle_kline(symbol_id, api_key):
    try:
        clean_key = api_key.strip()
        client = RestClient(api_key=clean_key)
        stock = client.stock
        
        candles = stock.intraday.candles(symbol=symbol_id)
        
        if not candles: return None, "回傳資料為空 (可能是代號錯誤)"
        if 'error' in candles: return None, f"API 錯誤: {candles.get('error')}"
        if 'data' not in candles: return None, "資料格式錯誤 (缺少 data 欄位)"
        
        data = candles['data']
        if not data: return None, "該股票今日尚無成交資料"

        df = pd.DataFrame(data)
        df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
        df['Date'] = pd.to_datetime(df['date'])
        df.set_index('Date', inplace=True)
        df.index = df.index.tz_convert('Asia/Taipei')
        
        return df[['Open', 'High', 'Low', 'Close', 'Volume']], None 

    except Exception as e:
        return None, str(e) 

# --- 3. 備用方案：Yahoo 即時 ---
@st.cache_data(ttl=30)
def get_realtime_quote_yahoo(symbol):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info.last_price
        if price and not np.isnan(price): return float(price)
    except: pass
    return None

# --- 工具：K 線重取樣 ---
def resample_data(df, timeframe_str):
    if timeframe_str == '1T': return df
    ohlc_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
    df_resampled = df.resample(timeframe_str).apply(ohlc_dict)
    df_resampled = df_resampled.dropna(subset=['Close'])
    return df_resampled

# --- 🔥 主邏輯：策略訊號產生器 (含接刀策略) ---
@st.cache_data(ttl=5)
def get_orb_signals(symbol_input, fugle_api_key=None, timeframe='1T', sentiment_score=50):
    symbol_id = symbol_input.split('.')[0]
    symbol_tw = f"{symbol_id}.TW"
    
    df = None
    source = "Yahoo (延遲/模擬)"
    fugle_error_msg = None
    
    # A. 優先嘗試 Fugle
    if fugle_api_key:
        df, error = get_fugle_kline(symbol_id, fugle_api_key)
        if df is not None and not df.empty:
            source = "Fugle (真即時 API)"
        else:
            fugle_error_msg = error
    
    # B. 降級使用 Yahoo
    if df is None or df.empty:
        try:
            ticker = yf.Ticker(symbol_tw)
            df = ticker.history(period="1d", interval="1m")
            realtime_price = get_realtime_quote_yahoo(symbol_tw)
            if not df.empty and realtime_price:
                last_time = df.index[-1]
                now = pd.Timestamp.now(tz='Asia/Taipei')
                if (now - last_time).total_seconds() > 120:
                    new_row = pd.DataFrame({'Open': [realtime_price], 'High': [realtime_price], 'Low': [realtime_price], 'Close': [realtime_price], 'Volume': [0]}, index=[now])
                    df = pd.concat([df, new_row])
        except: pass

    if df is None or df.empty:
        return None, {"error": "無法取得數據", "source": "None"}

    # 週期轉換
    if timeframe != '1T':
        df = resample_data(df, timeframe)

    # --- 取得昨日收盤價 (計算漲跌幅用) ---
    prev_close = 0
    trend = "Unknown"
    try:
        ticker_d = yf.Ticker(symbol_tw)
        df_daily = ticker_d.history(period="5d", interval="1d")
        if len(df_daily) >= 2:
            prev_close = df_daily['Close'].iloc[-2] # 昨天收盤
            # 簡單判斷趨勢
            ma5 = df_daily['Close'].rolling(5).mean().iloc[-1]
            trend = "Bullish" if df_daily['Close'].iloc[-1] > ma5 else "Bearish"
    except: pass
    
    # 如果抓不到 Prev Close，就用當日第一根 Open 代替 (雖不精準但可防崩潰)
    if prev_close == 0:
        prev_close = df['Open'].iloc[0]

    # --- 計算 VWAP ---
    df['Cum_Vol'] = df['Volume'].cumsum()
    df['Cum_Vol_Price'] = (df['Close'] * df['Volume']).cumsum()
    df['VWAP'] = df['Cum_Vol_Price'] / df['Cum_Vol']

    # --- 策略分流邏輯 ---
    entry_time, entry_price = None, None
    exit_time, exit_price = None, None
    signal_status = "等待訊號"
    strategy_name = "右側 VWAP" # 預設

    # 計算當前漲跌幅
    current_price = df['Close'].iloc[-1]
    pct_change = (current_price - prev_close) / prev_close
    
    # 🔥 策略 A: 左側接刀 (熱度 > 80)
    if sentiment_score > 80:
        strategy_name = "🔥 左側接刀"
        # 條件：現在價格比昨收跌 3% 以上
        if pct_change <= -0.03:
            # 為了標示在圖上，我們找第一個符合條件的 K 線
            for t, row in df.iterrows():
                row_change = (row['Close'] - prev_close) / prev_close
                if row_change <= -0.03:
                    entry_time = t
                    entry_price = row['Close']
                    break
        else:
            signal_status = f"未達接刀點 (-3%)，目前 {pct_change*100:.2f}%"

    # ⚖️ 策略 B: 右側 VWAP (熱度 <= 80)
    else:
        strategy_name = "⚖️ 右側 VWAP"
        # 原本的 VWAP 乖離策略
        market_open = df.index[0]
        scan_data = df
        max_dev = 0.0
        high_h = 0.0
        
        for t, row in scan_data.iterrows():
            if pd.isna(row['VWAP']): continue
            if row['High'] > high_h: high_h = row['High']
            dev = (row['Close'] - row['VWAP']) / row['VWAP']
            if dev > max_dev: max_dev = dev
                
            if not entry_time:
                if max_dev >= 0.006:
                    if high_h > 0 and row['Close'] < high_h * 0.994:
                        if row['Low'] <= row['VWAP'] * 1.015:
                            if row['Close'] > row['Open'] and row['Close'] >= row['VWAP']:
                                entry_time = t
                                entry_price = row['Close']
            # ... (出場邏輯簡化，因為主要是為了顯示進場)

    # 統一出場模擬 (簡單的停損停利，僅供視覺化)
    if entry_time:
        scan_exit = df[df.index > entry_time]
        for t, row in scan_exit.iterrows():
            # 簡單範例：賺 2% 或 賠 1.5% 出場
            if row['High'] >= entry_price * 1.02:
                exit_time = t; exit_price = entry_price * 1.02; break
            if row['Low'] <= entry_price * 0.985:
                exit_time = t; exit_price = entry_price * 0.985; break
        
        if exit_time: signal_status = "已出場"
        else: signal_status = f"持有中 {((current_price-entry_price)/entry_price)*100:.2f}%"

    stats = {
        "signal": signal_status, "signal_price": current_price,
        "entry_time": entry_time, "entry_price": entry_price,
        "exit_time": exit_time, "exit_price": exit_price,
        "vwap_data": df['VWAP'], "source": source,
        "context": {"trend": trend}, "is_realtime": (source == "Fugle (真即時 API)"),
        "fugle_error": fugle_error_msg,
        "strategy_name": strategy_name, # 回傳使用的策略名稱
        "pct_change": pct_change # 回傳漲跌幅
    }
    return df, stats

def backtest_strategy(symbol): return None
def backtest_past_week(symbol): return []