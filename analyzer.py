import yfinance as yf
import pandas as pd
import datetime
import twstock
import numpy as np
import time
import random
import streamlit as st
from fugle_marketdata import RestClient # 引入富果

# --- 熱門股池 ---
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

# --- 1. 海選部隊：使用 Yahoo 進行大量掃描 (維持防鎖機制) ---
@st.cache_data(ttl=900)
def screen_hot_stocks(limit=15):
    screened_list = []
    print("正在掃描市場熱門股 (Yahoo)...")
    
    for symbol_raw in MARKET_POOL:
        symbol = f"{symbol_raw}.TW" # Yahoo 需要 .TW
        time.sleep(random.uniform(0.1, 0.25)) # 稍微快一點，但保持禮貌
        
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
                screened_list.append({
                    'symbol': symbol,
                    'volatility': avg_volatility
                })
        except: continue
        
    screened_list.sort(key=lambda x: x['volatility'], reverse=True)
    return screened_list[:limit]

# --- 2. 特種部隊：使用 Fugle 進行精準打擊 (即時 K 線) ---
def get_fugle_kline(symbol_id, api_key):
    try:
        client = RestClient(api_key=api_key)
        stock = client.stock  # Initialize stock client
        
        # 抓取當日 K 線 (intraday candles)
        # 富果免費版限制：只能抓近期的，但對當沖夠用了
        candles = stock.intraday.candles(symbol=symbol_id)
        
        if not candles or 'data' not in candles:
            return None
        
        data = candles['data']
        if not data: return None

        df = pd.DataFrame(data)
        
        # 整理格式以符合我們策略的要求
        df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
        
        # 處理時間：富果回傳的是 UTC，要轉成台灣時間
        df['Date'] = pd.to_datetime(df['date'])
        df.set_index('Date', inplace=True)
        df.index = df.index.tz_convert('Asia/Taipei')
        
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]
    except Exception as e:
        print(f"Fugle Error: {e}")
        return None

# --- 3. 備用方案：Yahoo 即時 (當沒有 API Key 時) ---
@st.cache_data(ttl=30)
def get_realtime_quote_yahoo(symbol):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info.last_price
        if price and not np.isnan(price): return float(price)
    except: pass
    return None

# --- 主邏輯：策略訊號產生器 ---
@st.cache_data(ttl=5) # 如果用 API，快取可以縮短到 5 秒，甚至更短
def get_orb_signals(symbol_input, fugle_api_key=None):
    # 處理代號格式
    symbol_id = symbol_input.split('.')[0] # 2301
    symbol_tw = f"{symbol_id}.TW"          # 2301.TW
    
    df = None
    source = "Yahoo (延遲/模擬)"
    
    # A. 優先嘗試 Fugle (如果有 Key)
    if fugle_api_key:
        df = get_fugle_kline(symbol_id, fugle_api_key)
        if df is not None and not df.empty:
            source = "Fugle (真即時 API)"
    
    # B. 如果沒 Key 或 Fugle 失敗，使用 Yahoo + 人工補點
    if df is None or df.empty:
        try:
            ticker = yf.Ticker(symbol_tw)
            df = ticker.history(period="1d", interval="1m")
            
            # 嘗試補上最新價 (Stitching)
            realtime_price = get_realtime_quote_yahoo(symbol_tw)
            if not df.empty and realtime_price:
                last_time = df.index[-1]
                now = pd.Timestamp.now(tz='Asia/Taipei')
                if (now - last_time).total_seconds() > 120:
                    new_row = pd.DataFrame({
                        'Open': [realtime_price], 'High': [realtime_price],
                        'Low': [realtime_price], 'Close': [realtime_price], 'Volume': [0]
                    }, index=[now])
                    df = pd.concat([df, new_row])
        except: pass

    if df is None or df.empty:
        return None, {"error": "無法取得數據", "source": "None"}

    # --- 以下是策略運算 (通用邏輯) ---
    # 取得日線趨勢 (這部分永遠用 Yahoo，節省 Fugle 額度)
    try:
        ticker_d = yf.Ticker(symbol_tw)
        df_daily = ticker_d.history(period="3mo", interval="1d")
        
        if not df_daily.empty and len(df_daily) >= 20:
            df_daily['MA20'] = df_daily['Close'].rolling(window=20).mean()
            prev = df_daily.iloc[-2]
            trend = "Bullish" if prev['Close'] > prev['MA20'] else "Bearish"
            df_daily['Range'] = (df_daily['High'] - df_daily['Low']) / df_daily['Close'] * 100
            adr = df_daily['Range'].tail(5).mean()
            context = {"trend": trend, "adr_pct": adr}
        else:
            context = {"trend": "Unknown", "adr_pct": 0}
    except:
        context = {"trend": "Unknown", "adr_pct": 0}

    # VWAP 計算
    df['Cum_Vol'] = df['Volume'].cumsum()
    df['Cum_Vol_Price'] = (df['Close'] * df['Volume']).cumsum()
    df['VWAP'] = df['Cum_Vol_Price'] / df['Cum_Vol']

    # 策略判斷
    market_open = df.index[0]
    start_scan = market_open + pd.Timedelta(minutes=15)
    scan_data = df[df.index >= start_scan]
    
    entry_time, entry_price = None, None
    exit_time, exit_price = None, None
    max_dev = 0.0
    high_h = 0.0
    
    for t, row in scan_data.iterrows():
        if pd.isna(row['VWAP']): continue
        
        if row['High'] > high_h: high_h = row['High']
        dev = (row['Close'] - row['VWAP']) / row['VWAP']
        if dev > max_dev: max_dev = dev
            
        if not entry_time:
            # 策略：強度 > 0.6%, 回檔 > 0.6%, 支撐 1.5%
            if max_dev >= 0.006:
                if high_h > 0 and row['Close'] < high_h * 0.994:
                    if row['Low'] <= row['VWAP'] * 1.015:
                        if row['Close'] > row['Open'] and row['Close'] >= row['VWAP']:
                            entry_time = t
                            entry_price = row['Close']
        
        elif t > entry_time:
            # 出場：停損 1.5% 或 移動停利
            stop = entry_price * 0.985
            if row['High'] >= entry_price * 1.015: stop = max(stop, entry_price * 1.005)
            if row['High'] >= entry_price * 1.025: stop = max(stop, entry_price * 1.015)
            
            if row['Low'] <= stop:
                exit_time = t
                exit_price = stop
                break
    
    current_price = df['Close'].iloc[-1]
    signal_status = "等待訊號"
    if entry_time:
        if exit_time: signal_status = "已出場"
        else: signal_status = f"持有中 {((current_price-entry_price)/entry_price)*100:.2f}%"
    elif max_dev < 0.006:
        signal_status = "波動不足"

    stats = {
        "signal": signal_status, "signal_price": current_price,
        "entry_time": entry_time, "entry_price": entry_price,
        "exit_time": exit_time, "exit_price": exit_price,
        "vwap_data": df['VWAP'], "source": source,
        "context": context, "is_realtime": (source == "Fugle (真即時 API)")
    }
    return df, stats

# 為了相容性，保留空函式
def backtest_strategy(symbol): return None
def backtest_past_week(symbol): return []