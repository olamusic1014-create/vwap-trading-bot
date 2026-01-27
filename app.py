import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import pandas as pd
import time
import analyzer
from analyzer import get_orb_signals, screen_hot_stocks
import twstock

st.set_page_config(page_title="智能選股戰情室", layout="wide", page_icon="🛡️")

# --- 初始化 Session State ---
if 'target_symbol' not in st.session_state: st.session_state['target_symbol'] = "2301.TW"
if 'fugle_key' not in st.session_state: st.session_state['fugle_key'] = ""
if 'input_field' not in st.session_state: st.session_state['input_field'] = "2301"

# 🔥 核心升級：自動讀取雲端 Secrets
# 檢查 Streamlit 的保險箱裡有沒有 "FUGLE_KEY"
if "FUGLE_KEY" in st.secrets:
    st.session_state['fugle_key'] = st.secrets["FUGLE_KEY"]
    is_key_loaded = True
else:
    is_key_loaded = False

def get_stock_code(user_input):
    user_input = str(user_input).strip().upper()
    if user_input.endswith('.TW'):
        raw_code = user_input.replace('.TW', '')
        if raw_code.isdigit(): return user_input, raw_code
    if user_input.isdigit(): return f"{user_input}.TW", user_input
    for code, info in twstock.codes.items():
        if info.name == user_input: return f"{code}.TW", info.name
    return None, None

def update_symbol(symbol):
    st.session_state['target_symbol'] = symbol
    st.session_state['input_field'] = symbol.split('.')[0]

st.title("🛡️ VWAP 智能戰情室 (Fugle 加速版)")

# --- 側邊欄 ---
st.sidebar.header("設定")

# 🔥 根據是否自動載入 Key 顯示不同畫面
if is_key_loaded:
    st.sidebar.success("✅ API Key 已從雲端載入")
    # 這裡可以選擇不顯示 Key，或者顯示部分遮碼
    st.sidebar.caption("系統已自動連接富果 API")
else:
    # 如果沒設定 Secrets，才顯示手動輸入框
    api_key = st.sidebar.text_input("🔑 富果 API Key (選填)", value=st.session_state['fugle_key'], type="password")
    if api_key: st.session_state['fugle_key'] = api_key
    st.sidebar.info("💡 提示：你可以在 Streamlit Settings -> Secrets 設定 FUGLE_KEY，以後就不用手動輸入了！")

st.sidebar.divider()
user_input_val = st.sidebar.text_input("股票代號", key="input_field")
auto_refresh = st.sidebar.checkbox("🔄 即時監控 (每5秒)", value=False)
run_btn = st.sidebar.button("刷新")

st.sidebar.divider()
if st.sidebar.button("🔥 全市場智能選股"):
    with st.spinner("正在掃描市場 (使用 Yahoo 數據)..."):
        top_candidates = screen_hot_stocks(limit=15)
        st.session_state['scan_results'] = top_candidates

if user_input_val:
    code, name = get_stock_code(user_input_val)
    if code and code != st.session_state['target_symbol']:
        st.session_state['target_symbol'] = code

# --- 主畫面 ---
resolved_code, resolved_name = get_stock_code(st.session_state['target_symbol'])

if not resolved_code:
    st.error(f"無效代號: {st.session_state['target_symbol']}")
else:
    df, stats = get_orb_signals(resolved_code, st.session_state['fugle_key'])
    
    if df is not None:
        if stats.get('fugle_error'):
            st.warning(f"⚠️ 富果連線失敗，已切換回 Yahoo。原因：{stats['fugle_error']}")

        st.subheader(f"📊 {resolved_name} ({resolved_code})")
        
        src = stats.get('source', 'Unknown')
        src_color = "#00FF00" if "Fugle" in src else "orange"
        st.markdown(f"**資料來源:** <span style='color:{src_color}; font-weight:bold'>{src}</span>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        col1.metric("目前股價", f"{stats['signal_price']:.2f}")
        last_vwap = df['VWAP'].iloc[-1] if not df.empty and 'VWAP' in df.columns else 0
        col2.metric("VWAP", f"{last_vwap:.2f}")
        col3.metric("訊號狀態", stats['signal'])

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
        
        if auto_refresh:
            time.sleep(5) 
            st.rerun()

    else:
        st.error(f"無法取得數據 (Source: {stats.get('source')})")

if 'scan_results' in st.session_state and st.session_state['scan_results']:
    st.divider()
    st.subheader("🔥 智能選股結果")
    for item in st.session_state['scan_results']:
        c1, c2, c3 = st.columns([2, 2, 1])
        c1.write(item['symbol'])
        c2.write(f"波動率: {item['volatility']:.2f}%")
        target = item['symbol'].split('.')[0]
        c3.button("🔍", key=f"btn_{item['symbol']}", on_click=update_symbol, args=(f"{target}.TW",))