import yfinance as yf
import pandas as pd
import datetime
import twstock
import numpy as np
import time
import streamlit as st # 引入 streamlit 以使用快取功能

# --- 熱門股池 ---
MARKET_POOL = [
    '2330.TW', '2317.TW', '2454.TW', '2382.TW', '2303.TW', '2881.TW', '2891.TW', '2308.TW', '3711.TW', '3037.TW',
    '3035.TW', '3017.TW', '2368.TW', '3231.TW', '3443.TW', '3661.TW', '6669.TW', '2376.TW', '2356.TW', '2301.TW',
    '2603.TW', '2609.TW', '2615.TW', '2618.TW', '2610.TW', '2637.TW', 
    '1513.TW', '1519.TW', '1503.TW', '1504.TW', '1609.TW', 
    '3044.TW', '2383.TW', '6274.TW', '6213.TW', '2421.TW', '3013.TW', 
    '8046.TW', '8069.TW', '3533.TW', '3529.TW', '5269.TW', '3653.TW', 
    '2409.TW', '3481.TW', '6116.TW', '2481.TW', '3008.TW', 
    '2363.TW', '2344.TW', '2449.TW', '2313.TW', '2324.TW', 
    '3034.TW', '4961.TW', '4919.TW', '2458.TW', '3583.TW', 
    '2353.TW', '2323.TW', '2352.TW', '3260.TW', '6239.TW'
]

# 設定快取：1分鐘內不要重複抓即時報價
@st.cache_data(ttl=60)
def get_realtime_quote(symbol):
    try:
        stock_id = symbol.split('.')[0]
        realtime_data = twstock.realtime.get(stock_id)
        if realtime_data['success']:
            info = realtime_data['realtime']
            latest_price = info.get('latest_trade_price')
            if latest_price and latest_price != '-':
                return float(latest_price)
    except: pass
    return None

# 設定快取：15分鐘內不要重複執行全市場掃描 (避免被鎖 IP)
@st.cache_data(ttl=900)
def screen_hot_stocks(limit=15):
    screened_list = []
    print("正在掃描市場熱門股...")
    
    for symbol in MARKET_POOL:
        try:
            # 🔥 關鍵降速：每次請求休息 0.25 秒
            time.sleep(0.25)
            
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

# 設定快取：1小時內不要重複抓歷史回測 (歷史數據今天不會變)
@st.cache_data(ttl=3600)
def backtest_past_week(symbol):
    ticker = yf.Ticker(symbol)
    df_all = ticker.history(period="5d", interval="1m")
    
    if df_all.empty: return []

    daily_results = []
    grouped = df_all.groupby(df_all.index.date)
    
    for date, df in grouped:
        if len(df) < 30: continue 

        df['Cum_Vol'] = df['Volume'].cumsum()
        df['Cum_Vol_Price'] = (df['Close'] * df['Volume']).cumsum()
        df['VWAP'] = df['Cum_Vol_Price'] / df['Cum_Vol']
        
        entry_time = None
        entry_price = None
        exit_price = None
        status = "NO_SIGNAL"
        
        max_deviation = 0.0
        highest_high = 0.0
        
        start_time = df.index[0] + pd.Timedelta(minutes=15)
        scan_data = df[df.index >= start_time]
        
        for t, row in scan_data.iterrows():
            close = row['Close']
            low = row['Low']
            high = row['High']
            open_p = row['Open']
            vwap = row['VWAP']
            
            if high > highest_high: highest_high = high
            deviation = (close - vwap) / vwap
            if deviation > max_deviation: max_deviation = deviation
            
            if not entry_time:
                if max_deviation >= 0.006: 
                    if highest_high > 0 and close < highest_high * 0.994: 
                        if low <= vwap * 1.015: 
                            if close > open_p and close >= vwap: 
                                entry_time = t
                                entry_price = close
            
            if entry_time and t > entry_time:
                stop_price = entry_price * 0.985 
                if high >= entry_price * 1.015: stop_price = max(stop_price, entry_price * 1.005)
                if high >= entry_price * 1.025: stop_price = max(stop_price, entry_price * 1.015)
                
                if low <= stop_price:
                    exit_price = stop_price
                    status = "WIN" if exit_price > entry_price else "LOSS"
                    break
        
        if entry_time:
            if not exit_price: 
                exit_price = df['Close'].iloc[-1]
                status = "WIN" if exit_price > entry_price * 1.004 else "LOSS"
            
            raw_pnl = ((exit_price - entry_price) / entry_price) * 100
            net_pnl = raw_pnl - 0.4
        else:
            net_pnl = 0.0
            status = "NO_SIGNAL"
            
        daily_results.append({
            'date': date,
            'symbol': symbol,
            'status': status,
            'pnl': round(net_pnl, 2),
            'entry': round(entry_price, 2) if entry_price else 0,
            'exit': round(exit_price, 2) if exit_price else 0
        })
        
    return daily_results

# 設定快取：1分鐘內不要重複抓訊號
@st.cache_data(ttl=60)
def get_orb_signals(symbol):
    # 加入微小延遲，防止手動頻繁刷新時被鎖
    time.sleep(0.1) 
    
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="1d", interval="1m")
    df_daily = ticker.history(period="3mo", interval="1d")
    
    context = {"trend": "Neutral", "ma20": 0, "gap_percent": 0.0, "adr_pct": 0.0}
    if not df_daily.empty and len(df_daily) >= 20:
        df_daily['MA20'] = df_daily['Close'].rolling(window=20).mean()
        df_daily['Range_Pct'] = ((df_daily['High'] - df_daily['Low']) / df_daily['Close']) * 100
        adr_pct = df_daily['Range_Pct'].tail(5).mean()
        prev_day = df_daily.iloc[-2] if len(df_daily) >= 2 else df_daily.iloc[-1]
        trend = "Bullish" if prev_day['Close'] > prev_day['MA20'] else "Bearish"
        today_open = df['Open'].iloc[0] if not df.empty else 0
        gap_pct = 0.0
        if prev_day['Close'] > 0 and today_open > 0:
            gap_pct = ((today_open - prev_day['Close']) / prev_day['Close']) * 100
        context = {"trend": trend, "ma20": prev_day['MA20'], "gap_percent": gap_pct, "adr_pct": adr_pct}

    if df.empty: return None, {"error": "No data found"}

    df['Cum_Vol'] = df['Volume'].cumsum()
    df['Cum_Vol_Price'] = (df['Close'] * df['Volume']).cumsum()
    df['VWAP'] = df['Cum_Vol_Price'] / df['Cum_Vol']

    market_open_time = df.index[0]
    entry_time = None
    entry_price = None
    first_signal_type = None
    max_deviation = 0.0 
    highest_high = 0.0 
    
    start_scan_time = market_open_time + pd.Timedelta(minutes=15)
    scan_data = df[df.index >= start_scan_time]
    
    for t, row in scan_data.iterrows():
        vwap = row['VWAP']
        close = row['Close']
        low = row['Low']
        high = row['High']
        open_price = row['Open']
        
        if high > highest_high: highest_high = high
        deviation = (close - vwap) / vwap
        if deviation > max_deviation: max_deviation = deviation
            
        if max_deviation >= 0.006:
            if highest_high > 0 and close < highest_high * 0.994:
                if low <= vwap * 1.015:
                    if close > open_price and close >= vwap:
                        entry_time = t
                        entry_price = close
                        first_signal_type = "VWAP_DIP_BUY"
                        break

    exit_time = None
    exit_price = None
    exit_type = None 
    trailing_stop_history = []
    
    if entry_time:
        current_stop_price = entry_price * 0.985 
        trade_data = df[df.index > entry_time]
        for t, row in trade_data.iterrows():
            current_high = row['High']
            current_low = row['Low']
            trailing_stop_history.append((t, current_stop_price))
            if current_high >= entry_price * 1.015: current_stop_price = max(current_stop_price, entry_price * 1.005)
            if current_high >= entry_price * 1.025: current_stop_price = max(current_stop_price, entry_price * 1.015)
            if current_low <= current_stop_price:
                exit_time = t
                exit_price = current_stop_price
                exit_type = "WIN" if exit_price > entry_price else "LOSS"
                break

    realtime_price = get_realtime_quote(symbol)
    current_price = realtime_price if realtime_price else df['Close'].iloc[-1]
    
    current_signal = "等待訊號"
    if entry_time:
        if exit_time: current_signal = "已出場"
        else: current_signal = f"持有中 {((current_price-entry_price)/entry_price)*100:.2f}%"
    elif max_deviation < 0.006: current_signal = "波動不足"
    
    stats = {
        "orb_high": 0, "orb_low": 0, "signal": current_signal,
        "signal_price": current_price, "entry_time": entry_time, "entry_price": entry_price,
        "entry_type": first_signal_type, "exit_time": exit_time, "exit_price": exit_price,
        "exit_type": exit_type, "context": context, "is_realtime": (realtime_price is not None),
        "buffer_price": 0, "vwap_data": df['VWAP'], "stop_history": trailing_stop_history
    }
    return df, stats

def backtest_strategy(symbol):
    try:
        # 重用 get_orb_signals 邏輯，它現在有快取了，所以跑起來會很快
        df, stats = get_orb_signals(symbol)
        adr = stats.get('context', {}).get('adr_pct', 0)
        
        if stats.get("error"): return {'symbol': symbol, 'status': 'ERROR', 'pnl': 0.0, 'adr': adr, 'signal_type': 'None'}
        if not stats.get('entry_time'):
             return {'symbol': symbol, 'status': 'NO_SIGNAL', 'pnl': 0.0, 'signal_type': 'None', 'adr': round(adr, 2)}

        entry_price = stats['entry_price']
        exit_price = stats.get('exit_price')
        exit_type = stats.get('exit_type')
        
        status = "HOLD"
        if exit_price:
            status = "WIN" if exit_price > entry_price * 1.004 else "LOSS"
            if "WIN" in str(exit_type): status = "WIN_TRAIL"
        else:
            exit_price = df['Close'].iloc[-1]

        raw_pnl = ((exit_price - entry_price) / entry_price) * 100
        net_pnl = raw_pnl - 0.4
        final_status = "WIN" if net_pnl > 0 else "LOSS"
        if "TRAIL" in status and net_pnl > 0: final_status = "WIN (Trail)"

        return {
            'symbol': symbol, 'status': final_status, 'pnl': round(net_pnl, 2),
            'entry': round(entry_price, 2), 'exit': round(exit_price, 2), 'signal_type': stats['entry_type'], 'adr': round(adr, 2)
        }
    except:
        return {'symbol': symbol, 'status': 'ERROR', 'pnl': 0.0, 'adr': 0, 'signal_type': 'None'}