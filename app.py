import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import analyzer
from analyzer import get_orb_signals, screen_hot_stocks
import twstock
import time

# 1. 頁面設定 (移除頂部 padding，讓內容貼頂)
st.set_page_config(page_title="戰情室", layout="wide", page_icon="🛡️")

# 2. 注入 CSS：防閃爍 + 極致壓縮版面
st.markdown("""
    <style>
    /* 隱藏卷軸 & Loading 遮罩 */
    div[data-testid="stFragment"] ::-webkit-scrollbar { display: none !important; width: 0px !important; }
    div[data-testid="stFragment"] { scrollbar-width: none !important; overflow: hidden !important; animation: none !important; transition: none !important; opacity: 1 !important; }
    div[class*="stShim"] { display: none !important; }
    
    /* 圖表背景黑化 */
    div[data-testid="stPlotlyChart"] { background-color: #0E1117 !important; }
    iframe { background-color: #0E1117 !important; }
    
    /* 🔥 極致壓縮：移除所有頂部留白 */
    .block-container { 
        padding-top: 0.1rem !important; 
        padding-bottom: 2rem !important; 
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    header { visibility: hidden !important; } /* 隱藏 Streamlit 頂部漢堡選單列 (可選) */
    
    /* 讓輸入框更緊湊 */
    div[data-testid="stTextInput"] { margin-bottom: 0px !important; }
    div[data-testid="stSelectbox"] { margin-bottom: 0px !important; }
    div[data-testid="stCheckbox"] { margin-top: 5px !important; }
    </style>
""", unsafe_allow_html=True)

# 3. 初始化 Session State
if 'target_symbol' not in st.session_state: st.session_state['target_symbol'] = "2301.TW"
if 'fugle_key' not in st.session_state: st.session_state['fugle_key'] = ""
if 'input_field' not in st.session_state: st.session_state['input_field'] = "2301"
if 'pending_restart' not in st.session_state: st.session_state['pending_restart'] = False
if 'scan_results' not in st.session_state: st.session_state['scan_results'] = []

# 4. 讀取 Secrets
if "FUGLE_KEY" in st.secrets:
    st.session_state['fugle_key'] = st.secrets["FUGLE_KEY"]
    is_key_loaded = True
else:
    is_key_loaded = False

# 5. Helper Functions
def reset_monitor():
    if st.session_state.get('auto_refresh_state'): 
        st.session_state['auto_refresh_state'] = False 
        st.session_state['pending_restart'] = True    

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
    reset_monitor()

# 自動重啟邏輯
if st.session_state['pending_restart']:
    with st.spinner("⏳..."):
        time.sleep(0.5) 
        st.session_state['pending_restart'] = False 
        st.session_state['auto_refresh_state'] = True 
        st.rerun()

# --- 頂部控制列 (緊湊佈局) ---
c1, c2, c3 = st.columns([1.2, 0.8, 1])

with c1:
    user_input_val = st.text_input("代號", key="input_field", on_change=reset_monitor, label_visibility="collapsed", placeholder="股票代號")

with c2:
    timeframe_map = {"1分": "1T", "5分": "5T", "15分": "15T", "30分": "30T", "60分": "60T"}
    selected_tf_label = st.selectbox("週期", list(timeframe_map.keys()), index=0, on_change=reset_monitor, label_visibility="collapsed")
    selected_tf_code = timeframe_map[selected_tf_label]

with c3:
    auto_refresh = st.toggle("監控", value=False, key="auto_refresh_state")

# 7. 核心邏輯
if user_input_val:
    code, name = get_stock_code(user_input_val)
    if code and code != st.session_state['target_symbol']:
        st.session_state['target_symbol'] = code

# 🔥 確保變數已定義 (防止 NameError)
resolved_code, resolved_name = get_stock_code(st.session_state['target_symbol'])

# 8. Fragment 儀表板
@st.fragment(run_every=5 if auto_refresh else None)
def display_dashboard():
    if not resolved_code: return

    with st.container(height=650, border=False):
        df, stats = get_orb_signals(resolved_code, st.session_state['fugle_key'], timeframe=selected_tf_code)
        
        if df is not None:
            # 計算顏色
            current_price = stats['signal_price']
            last_vwap = df['VWAP'].iloc[-1] if not df.empty and 'VWAP' in df.columns else 0
            price_color = "#FF5252" if current_price > last_vwap else "#00E676"
            
            # 🔥 HUD 修復版：移除所有縮排，確保 HTML 正確渲染 🔥
            # 並使用 display:flex 讓它變成單行
            hud_html = f"""
<div style="display: flex; justify-content: space-between; align-items: center; background-color: #262730; padding: 5px 10px; border-radius: 6px; border: 1px solid #444; margin-bottom: 5px; margin-top: 5px;">
    <div style="display: flex; align-items: baseline; gap: 8px;">
        <span style="font-size: 1rem; font-weight: bold; color: #FFF;">{resolved_code}</span>
        <span style="font-size: 1.4rem; font-weight: bold; color: {price_color};">{current_price:.2f}</span>
    </div>
    <div style="text-align: right; line-height: 1;">
        <div style="font-size: 0.75rem; color: #CCC;">VWAP <span style="color: yellow; font-weight: bold;">{last_vwap:.2f}</span></div>
        <div style="font-size: 0.75rem; color: #888;">{stats['signal']}</div>
    </div>
</div>
"""
            st.markdown(hud_html, unsafe_allow_html=True)

            # 繪圖
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="價格"))
            
            if 'vwap_data' in stats:
                fig.add_trace(go.Scatter(x=df.index, y=stats['vwap_data'], mode='lines', line=dict(color='yellow', width=2), name="VWAP"))
            
            if stats.get('entry_time'):
                fig.add_trace(go.Scatter(x=[stats['entry_time']], y=[stats['entry_price']], mode='markers', marker=dict(size=15, color='#FFD700'), name="買進"))
            if stats.get('exit_time'):
                 fig.add_trace(go.Scatter(x=[stats['exit_time']], y=[stats['exit_price']], mode='markers', marker=dict(size=15, color='red', symbol='x', line=dict(width=2, color='white')), name="出場"))

            # 🔥 圖表設定：縮放視角鎖定
            fig.update_layout(
                height=450, # 加大高度，因為省下了標題和HUD的空間
                template="plotly_dark", 
                plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', font=dict(color='white'),
                xaxis=dict(showgrid=True, gridcolor='#333', type='category'),
                yaxis=dict(showgrid=True, gridcolor='#333'),
                margin=dict(l=0, r=0, t=5, b=0),
                uirevision=resolved_code, # 👈 鎖定縮放：只要代號沒變，縮放就不變
                transition={'duration': 0} 
            )
            
            st.plotly_chart(fig, use_container_width=True, key="live_chart_fragment", config={'displayModeBar': False})
        else:
            st.error("無法取得數據")

# 9. 執行儀表板
if resolved_code:
    display_dashboard()
else:
    st.warning("請輸入股票代號")

# --- 底部折疊區 (設定與選股) ---
# 移到最下面，不佔用看盤視線
with st.expander("🛠️ 進階設定 / 全市場選股"):
    if is_key_loaded:
        st.success("✅ API Key 已載入")
    else:
        api_key = st.text_input("🔑 富果 API Key", value=st.session_state['fugle_key'], type="password")
        if api_key: st.session_state['fugle_key'] = api_key
    
    if st.button("🔥 掃描全市場熱門股"):
        with st.spinner("掃描中..."):
            st.session_state['scan_results'] = screen_hot_stocks(limit=15)

# 選股結果列表
if st.session_state['scan_results']:
    st.divider()
    st.markdown("##### 掃描結果")
    for item in st.session_state['scan_results']:
        c1, c2, c3 = st.columns([2, 2, 1])
        c1.write(f"**{item['symbol']}**")
        c2.write(f"波: {item['volatility']:.1f}%")
        target = item['symbol'].split('.')[0]
        c3.button("🔍", key=f"btn_{item['symbol']}", on_click=update_symbol, args=(f"{target}.TW",))