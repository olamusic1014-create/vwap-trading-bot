import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import pandas as pd
import time
import analyzer
from analyzer import get_orb_signals, screen_hot_stocks
import twstock

st.set_page_config(page_title="智能選股戰情室", layout="wide", page_icon="🛡️")

if 'target_symbol' not in st.session_state: st.session_state['target_symbol'] = "2301.TW"
if 'fugle_key' not in st.session_state: st.session_state['fugle_key'] = ""
if 'input_field' not in st.session_state: st.session_state['input_field'] = "2301"

# 🔥 修復：增強代號判斷邏輯
def get_stock_code(user_input):
    user_input = str(user_input).strip().upper()
    
    # 情況 1: 已經是完整代號 (如 2301.TW)
    if user_input.endswith('.TW'):
        raw_code = user_input.replace('.TW', '')
        if raw_code.isdigit():
            return user_input, raw_code # 直接回傳
            
    # 情況 2: 純數字 (如 2301)
    if user_input.isdigit(): 
        return f"{user_input}.TW", user_input
    
    # 情況 3: 中文名稱 (如 台積電)
    for code, info in twstock.codes.items():
        if info.name == user_input: 
            return f"{code}.TW", info.name
            
    return None, None

def update_symbol(symbol):
    st.session_state['target_symbol'] = symbol
    # 更新輸入框顯示 (去掉 .TW 比較好看)
    st.session_state['input_field'] = symbol.split('.')[0]

st.title("🛡️ VWAP 智能戰情室 (Fugle 加速版)")

# --- 側邊欄 ---
st.sidebar.header("設定")
# API Key 輸入區
api_key = st.sidebar.text_input("🔑 富果 API Key (選填)", value=st.session_state['fugle_key'], type="password")
if api_key: st.session_state['fugle_key'] = api_key

st.sidebar.divider()
# 股票代號輸入區
user_input_val = st.sidebar.text_input("股票代號", key="input_field")
auto_refresh = st.sidebar.checkbox("🔄 即時監控 (每5秒)", value=False)
run_btn = st.sidebar.button("刷新")

st.sidebar.divider()
if st.sidebar.button("🔥 全市場智能選股"):
    with st.spinner("正在掃描市場 (使用 Yahoo 數據)..."):
        top_candidates = screen_hot_stocks(limit=15)
        st.session_state['scan_results'] = top_candidates

# 處理使用者輸入
if user_input_val:
    code, name = get_stock_code(user_input_val)
    if code and code != st.session_state['target_symbol']:
        st.session_state['target_symbol'] = code

# --- 主畫面 ---
resolved_code, resolved_name = get_stock_code(st.session_state['target_symbol'])

if not resolved_code:
    st.error(f"無效代號: {st.session_state['target_symbol']}")
else:
    # 呼叫 analyzer，傳入 API Key
    df, stats = get_orb_signals(resolved_code, st.session_state['fugle_key'])
    
    if df is not None:
        st.subheader(f"📊 {resolved_name} ({resolved_code})")
        
        # 顯示資料來源狀態
        src = stats.get('source', 'Unknown')
        # 如果是 Fugle 來源，顯示綠色；否則顯示橘色
        src_color = "#00FF00" if "Fugle" in src else "orange"
        st.markdown(f"**資料來源:** <span style='color:{src_color}; font-weight:bold'>{src}</span>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        col1.metric("目前股價", f"{stats['signal_price']:.2f}")
        # 安全讀取 VWAP，避免空值報錯
        last_vwap = df['VWAP'].iloc[-1] if not df.empty and 'VWAP' in df.columns else 0
        col2.metric("VWAP", f"{last_vwap:.2f}")
        col3.metric("訊號狀態", stats['signal'])

        # 繪圖
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="價格"))
        if 'vwap_data' in stats:
            fig.add_trace(go.Scatter(x=df.index, y=stats['vwap_data'], mode='lines', line=dict(color='yellow', width=2), name="VWAP"))
        
        if stats.get('entry_time'):
            fig.add_trace(go.Scatter(x=[stats['entry_time']], y=[stats['entry_price']], mode='markers', marker=dict(size=15, color='#FFD700'), name="買進"))
        if stats.get('exit_time'):
             fig.add_trace(go.Scatter(x=[stats['exit_time']], y=[stats['exit_price']], mode='markers', marker=dict(size=15, color='red', symbol='x', line=dict(width=2, color='white')), name="出場"))

        fig.update_layout(
            height=450, template="plotly_dark", 
            plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', font=dict(color='white'),
            xaxis=dict(showgrid=True, gridcolor='#333'), yaxis=dict(showgrid=True, gridcolor='#333'),
            margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # 自動刷新邏輯
        if auto_refresh:
            time.sleep(5) 
            st.rerun()

    else:
        st.error(f"無法取得數據 (Source: {stats.get('source')})")

# --- 顯示選股結果 ---
if 'scan_results' in st.session_state and st.session_state['scan_results']:
    st.divider()
    st.subheader("🔥 智能選股結果")
    for item in st.session_state['scan_results']:
        c1, c2, c3 = st.columns([2, 2, 1])
        c1.write(item['symbol'])
        c2.write(f"波動率: {item['volatility']:.2f}%")
        target = item['symbol'].split('.')[0]
        c3.button("🔍", key=f"btn_{item['symbol']}", on_click=update_symbol, args=(f"{target}.TW",))