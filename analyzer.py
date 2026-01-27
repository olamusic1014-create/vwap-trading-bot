import yfinance as yf
import pandas as pd
import datetime
import twstock
import numpy as np
import time
import random
import streamlit as st
from fugle_marketdata import RestClient 

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
        
        # 抓取 1 分 K (最細顆粒度)
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

# --- 工具：K 線重取樣 (Resampling) ---
def resample_data(df, timeframe_str):
    """
    將 1 分 K 資料轉換成其他週期 (5分, 15分...)
    timeframe_str: '1T', '5T', '15T', '30T', '60T'
    """
    if timeframe_str == '1T':
        return df
    
    # 定義轉換規則
    ohlc_dict = {
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }
    
    # 執行 Resample
    df_resampled = df.resample(timeframe_str).apply(ohlc_dict)
    
    # 移除沒有交易的時段 (dropna)
    df_resampled = df_resampled.dropna(subset=['Close'])
    
    return df_resampled

# --- 主邏輯 ---
@st.cache_data(ttl=5)
def get_orb_signals(symbol_input, fugle_api_key=None, timeframe='1T'):
    symbol_id = symbol_input.split('.')[0]
    symbol_tw = f"{symbol_id}.TW"
    
    df = None
    source = "Yahoo (延遲/模擬)"
    fugle_error_msg = None
    
    # A. 優先嘗試 Fugle (抓 1 分 K)
    if fugle_api_key:
        df, error = get_fugle_kline(symbol_id, fugle_api_key)
        if df is not None and not df.empty:
            source = "Fugle (真即時 API)"
        else:
            fugle_error_msg = error
    
    # B. 降級使用 Yahoo (抓 1 分 K)
    if df is None or df.empty:
        try:
            ticker = yf.Ticker(symbol_tw)
            df = ticker.history(period="1d", interval="1m")
            realtime_price = get_realtime_quote_yahoo(symbol_tw)
            
            # 補點邏輯
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

    # 🔥 關鍵步驟：在這裡進行週期轉換 (1分 -> 5分/15分...)
    # 這樣最新的補點也會被正確歸類到當下的 5 分 K 裡
    if timeframe != '1T':
        df = resample_data(df, timeframe)

    # --- 策略運算 (基於轉換後的 df) ---
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

    # VWAP 計算 (會根據新的週期重新計算)
    df['Cum_Vol'] = df['Volume'].cumsum()
    df['Cum_Vol_Price'] = (df['Close'] * df['Volume']).cumsum()
    df['VWAP'] = df['Cum_Vol_Price'] / df['Cum_Vol']

    # 策略邏輯適應新週期
    market_open = df.index[0]
    # 根據週期調整掃描起始點 (避免剛開盤指標不穩)
    scan_offset = 15 if timeframe == '1T' else 1 
    # 如果是 5 分 K，前面幾根就可以開始看了
    
    start_scan = market_open # + pd.Timedelta(minutes=scan_offset) 
    # 簡化邏輯：全掃描，但 VWAP 需要一點量才準
    
    scan_data = df # 掃描所有 K 棒
    
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
            # 注意：這裡的條件 (0.6% 乖離) 是針對 1 分 K 設計的
            # 切換到長週期時，這些條件可能比較難觸發，這是正常的
            if max_dev >= 0.006:
                if high_h > 0 and row['Close'] < high_h * 0.994:
                    if row['Low'] <= row['VWAP'] * 1.015:
                        if row['Close'] > row['Open'] and row['Close'] >= row['VWAP']:
                            entry_time = t
                            entry_price = row['Close']
        elif t > entry_time:
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
        "context": context, "is_realtime": (source == "Fugle (真即時 API)"),
        "fugle_error": fugle_error_msg
    }
    return df, stats

def backtest_strategy(symbol): return None
def backtest_past_week(symbol): return []