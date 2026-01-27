import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import analyzer
from analyzer import get_orb_signals, screen_hot_stocks
import twstock
import time

# 1. 頁面設定
st.set_page_config(page_title="智能選股戰情室", layout="wide", page_icon="🛡️")

# 2. 注入 CSS：防閃爍 + 手機版優化
st.markdown("""
    <style>
    /* 隱藏卷軸 */
    div[data-testid="stFragment"] ::-webkit-scrollbar { display: none !important; width: 0px !important; }
    div[data-testid="stFragment"] { scrollbar-width: none !important; overflow: hidden !important; }
    
    /* 隱藏 Loading 遮罩 */
    div[data-testid="stFragment"] { animation: none !important; transition: none !important; opacity: 1 !important; }
    div[class*="stShim"] { display: none !important; }
    
    /* 圖表背景黑化 */
    div[data-testid="stPlotlyChart"] { background-color: #0E1117 !important; }
    iframe { background-color: #0E1117 !important; }
    
    /* 手機版優化：減少頂部留白，讓控制列更靠上 */
    .block-container { padding-top: 1rem !important; padding-bottom: 5rem !important; }
    
    /* 讓輸入框在手機上更好點 */
    div[data-testid="stTextInput"] input { font-size: 16px !important; }
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
    """參數改變時，強制關閉監控並重啟"""
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

# 🔥 自動重啟邏輯 (放在最上面)
if st.session_state['pending_restart']:
    with st.spinner("⏳ 正在切換並重啟監控..."):
        time.sleep(0.5) 
        st.session_state['pending_restart'] = False 
        st.session_state['auto_refresh_state'] = True 
        st.rerun()

# 6. 主畫面 UI (手機版佈局)
st.title("🛡️ VWAP 戰情室")

# --- 頂部折疊區 (放 API Key 和 選股功能) ---
with st.expander("⚙️ 設定 / 全市場選股 (點擊展開)"):
    if is_key_loaded:
        st.success("✅ API Key 已載入")
    else:
        api_key = st.text_input("🔑 富果 API Key", value=st.session_state['fugle_key'], type="password")
        if api_key: st.session_state['fugle_key'] = api_key
    
    if st.button("🔥 掃描全市場熱門股"):
        with st.spinner("掃描中..."):
            st.session_state['scan_results'] = screen_hot_stocks(limit=15)

# --- 核心控制區 (直接顯示在畫面頂部) ---
# 使用 columns 讓輸入框並排，節省手機空間
c1, c2 = st.columns([1.5, 1])

with c1:
    # 股票輸入框
    user_input_val = st.text_input("股票代號", key="input_field", on_change=reset_monitor)

with c2:
    # 週期選擇
    timeframe_map = {"1分": "1T", "5分": "5T", "15分": "15T", "30分": "30T", "60分": "60T"}
    selected_tf_label = st.selectbox("週期", list(timeframe_map.keys()), index=0, on_change=reset_monitor)
    selected_tf_code = timeframe_map[selected_tf_label]

# 即時監控開關 (獨立一行，大按鈕)
auto_refresh = st.toggle("🔄 啟用即時監控", value=False, key="auto_refresh_state")

# 7. 核心邏輯
if user_input_val:
    code, name = get_stock_code(user_input_val)
    if code and code != st.session_state['target_symbol']:
        st.session_state['target_symbol'] = code

resolved_code, resolved_name = get_stock_code(st.session_state['target_symbol'])

# 8. Fragment 儀表板
@st.fragment(run_every=5 if auto_refresh else None)
def display_dashboard():
    if not resolved_code: return

    with st.container(height=650, border=False):
        df, stats = get_orb_signals(resolved_code, st.session_state['fugle_key'], timeframe=selected_tf_code)
        
        if df is not None:
            # 簡化標題顯示，節省空間
            st.markdown(f"### {resolved_name} `{resolved_code}`")
            
            # 數據狀態列
            src = stats.get('source', 'Unknown')
            src_color = "#00FF00" if "Fugle" in src else "orange"
            
            # 使用 HTML 做更緊湊的排版
            st.markdown(
                f"""
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <div><span style='color:gray; font-size:0.8rem'>來源:</span> <span style='color:{src_color}; font-weight:bold; font-size:0.8rem'>{src}</span></div>
                    <div><span style='color:gray; font-size:0.8rem'>狀態:</span> <span style='font-weight:bold'>{stats['signal']}</span></div>
                </div>
                """, 
                unsafe_allow_html=True
            )
            
            # 價格大字顯示
            c_price, c_vwap = st.columns(2)
            c_price.metric("現價", f"{stats['signal_price']:.2f}")
            last_vwap = df['VWAP'].iloc[-1] if not df.empty and 'VWAP' in df.columns else 0
            c_vwap.metric("VWAP", f"{last_vwap:.2f}")

            # 繪圖
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="價格"))
            
            if 'vwap_data' in stats:
                fig.add_trace(go.Scatter(x=df.index, y=stats['vwap_data'], mode='lines', line=dict(color='yellow', width=2), name="VWAP"))
            
            if stats.get('entry_time'):
                fig.add_trace(go.Scatter(x=[stats['entry_time']], y=[stats['entry_price']], mode='markers', marker=dict(size=15, color='#FFD700'), name="買進"))
            if stats.get('exit_time'):
                 fig.add_trace(go.Scatter(x=[stats['exit_time']], y=[stats['exit_price']], mode='markers', marker=dict(size=15, color='red', symbol='x', line=dict(width=2, color='white')), name="出場"))

            # 🔥🔥🔥 縮放視角鎖定核心 🔥🔥🔥
            # uirevision=resolved_code 的意思是：
            # 「只要 resolved_code (股票代號) 沒變，使用者的縮放/平移狀態就不要重置！」
            # 只有當你切換股票時，圖表才會重置回預設視角。
            fig.update_layout(
                height=380,
                template="plotly_dark", 
                plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', font=dict(color='white'),
                xaxis=dict(showgrid=True, gridcolor='#333', type='category'),
                yaxis=dict(showgrid=True, gridcolor='#333'),
                margin=dict(l=0, r=0, t=10, b=0),
                uirevision=resolved_code, # 👈 這行是縮放不跳掉的關鍵
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

# 10. 選股結果 (放在最下方)
if st.session_state['scan_results']:
    st.divider()
    st.markdown("##### 🔥 掃描結果") # 標題改小一點
    for item in st.session_state['scan_results']:
        c1, c2, c3 = st.columns([2, 2, 1])
        c1.write(f"**{item['symbol']}**")
        c2.write(f"波: {item['volatility']:.1f}%")
        target = item['symbol'].split('.')[0]
        c3.button("🔍", key=f"btn_{item['symbol']}", on_click=update_symbol, args=(f"{target}.TW",))