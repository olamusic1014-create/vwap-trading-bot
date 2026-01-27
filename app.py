import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import analyzer
from analyzer import get_orb_signals, screen_hot_stocks
import twstock
import time

# 1. 頁面設定 (必須在第一行)
st.set_page_config(page_title="智能選股戰情室", layout="wide", page_icon="🛡️")

# 2. 注入終極防閃爍 CSS
st.markdown("""
    <style>
    /* --------------------------------------------------
       1. 卷軸隱藏術：防止版面因為卷軸出現而跳動
    -------------------------------------------------- */
    /* 針對 Chrome/Safari/Edge 隱藏卷軸 */
    div[data-testid="stFragment"] ::-webkit-scrollbar {
        display: none !important;
        width: 0px !important;
    }
    /* 針對 Firefox */
    div[data-testid="stFragment"] {
        scrollbar-width: none !important;
        overflow: hidden !important; /* 強制隱藏溢出內容 */
    }

    /* --------------------------------------------------
       2. 防閃爍術：消滅 Streamlit 的 Loading 灰色遮罩
    -------------------------------------------------- */
    div[data-testid="stFragment"] {
        animation: none !important;
        transition: none !important;
        opacity: 1 !important; /* 強制不透明 */
    }
    div[class*="stShim"] {
        display: none !important; /* 隱藏載入中的灰色方塊 */
    }

    /* --------------------------------------------------
       3. 防白光術：強制圖表底層變黑
       這是解決「閃一下」最關鍵的一步！
    -------------------------------------------------- */
    div[data-testid="stPlotlyChart"] {
        background-color: #0E1117 !important;
    }
    iframe {
        background-color: #0E1117 !important; /* 讓 iframe 預設背景就是黑的 */
    }
    
    /* 調整頂部間距，讓畫面更緊湊 */
    .block-container {
        padding-top: 1rem !important;
    }
    </style>
""", unsafe_allow_html=True)

# 3. 初始化 Session State
if 'target_symbol' not in st.session_state: st.session_state['target_symbol'] = "2301.TW"
if 'fugle_key' not in st.session_state: st.session_state['fugle_key'] = ""
if 'input_field' not in st.session_state: st.session_state['input_field'] = "2301"
if 'pending_restart' not in st.session_state: st.session_state['pending_restart'] = False

# 4. 讀取 Secrets
if "FUGLE_KEY" in st.secrets:
    st.session_state['fugle_key'] = st.secrets["FUGLE_KEY"]
    is_key_loaded = True
else:
    is_key_loaded = False

# 5. 定義 Helper Functions
def reset_monitor():
    """當參數改變時，強制重啟監控"""
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

# 6. 側邊欄 UI
st.title("🛡️ VWAP 智能戰情室 (Fugle 加速版)")
st.sidebar.header("設定")

if is_key_loaded:
    st.sidebar.success("✅ API Key 已從雲端載入")
else:
    api_key = st.sidebar.text_input("🔑 富果 API Key (選填)", value=st.session_state['fugle_key'], type="password")
    if api_key: st.session_state['fugle_key'] = api_key

st.sidebar.divider()

# 輸入框與選單 (綁定 reset_monitor)
user_input_val = st.sidebar.text_input("股票代號", key="input_field", on_change=reset_monitor)

timeframe_map = {"1 分鐘": "1T", "5 分鐘": "5T", "15 分鐘": "15T", "30 分鐘": "30T", "60 分鐘": "60T"}
selected_tf_label = st.sidebar.selectbox("K 線週期", list(timeframe_map.keys()), index=0, on_change=reset_monitor)
selected_tf_code = timeframe_map[selected_tf_label]

auto_refresh = st.sidebar.toggle("🔄 啟用即時監控 (專注模式)", value=False, key="auto_refresh_state")

# 自動重啟邏輯
if st.session_state['pending_restart']:
    st.sidebar.warning("⏳ 參數調整中，即將重啟監控...")
    time.sleep(1) 
    st.session_state['pending_restart'] = False 
    st.session_state['auto_refresh_state'] = True 
    st.rerun() 

st.sidebar.divider()
if st.sidebar.button("🔥 全市場智能選股"):
    with st.spinner("正在掃描市場 (使用 Yahoo 數據)..."):
        top_candidates = screen_hot_stocks(limit=15)
        st.session_state['scan_results'] = top_candidates

# 7. 核心邏輯 (處理輸入與變數定義)
if user_input_val:
    code, name = get_stock_code(user_input_val)
    if code and code != st.session_state['target_symbol']:
        st.session_state['target_symbol'] = code

# 🔥🔥🔥 關鍵修正：在這裡定義 resolved_code，確保全域可見 🔥🔥🔥
resolved_code, resolved_name = get_stock_code(st.session_state['target_symbol'])

if not resolved_code:
    st.error(f"無效代號: {st.session_state['target_symbol']}")

# 8. Fragment 儀表板定義
# 只有當 resolved_code 存在時，這個函數才會有意義
@st.fragment(run_every=5 if auto_refresh else None)
def display_dashboard():
    # 再次檢查，雖然外面檢查過了，但為了 fragment 的獨立性，保險起見
    if not resolved_code: return

    # 🔥 容器高度設為 680px (比之前更大)，確保絕對不會出現卷軸
    with st.container(height=680, border=False):
        
        df, stats = get_orb_signals(resolved_code, st.session_state['fugle_key'], timeframe=selected_tf_code)
        
        if df is not None:
            if stats.get('fugle_error'):
                st.warning(f"⚠️ 富果連線失敗，已切換回 Yahoo。原因：{stats['fugle_error']}")

            st.subheader(f"📊 {resolved_name} ({resolved_code}) - {selected_tf_label}")
            
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

            # 🔥 圖表高度設為 400px，保留下方約 150px 的緩衝區給卷軸 (如果有)
            # 這樣就算卷軸出現，也只會在下方空白處，不會擠壓到圖表
            fig.update_layout(
                height=400,
                template="plotly_dark", 
                plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', font=dict(color='white'),
                xaxis=dict(showgrid=True, gridcolor='#333', type='category'),
                yaxis=dict(showgrid=True, gridcolor='#333'),
                margin=dict(l=0, r=0, t=10, b=0),
                uirevision='constant', # 鎖定視角
                transition={'duration': 0} # 關閉動畫
            )
            
            # 關閉 ModeBar 減少視覺干擾
            st.plotly_chart(
                fig, 
                use_container_width=True, 
                key="live_chart_fragment",
                config={'displayModeBar': False} 
            )
            
        else:
            st.error(f"無法取得數據 (Source: {stats.get('source')})")

# 9. 執行儀表板 (只有在代號有效時才執行)
if resolved_code:
    display_dashboard()

# 10. 選股結果顯示區
if 'scan_results' in st.session_state and st.session_state['scan_results']:
    st.divider()
    st.subheader("🔥 智能選股結果")
    for item in st.session_state['scan_results']:
        c1, c2, c3 = st.columns([2, 2, 1])
        c1.write(item['symbol'])
        c2.write(f"波動率: {item['volatility']:.2f}%")
        target = item['symbol'].split('.')[0]
        c3.button("🔍", key=f"btn_{item['symbol']}", on_click=update_symbol, args=(f"{target}.TW",))