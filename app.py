import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import analyzer
from analyzer import get_orb_signals, screen_hot_stocks
import twstock
import time
import asyncio

# 🔥 嘗試匯入爬蟲模組
HAS_HEAT_MODULE = False
HEAT_ERROR = ""
try:
    import stock_heat_analyzer as heat
    HAS_HEAT_MODULE = True
except Exception as e:
    HEAT_ERROR = str(e)

# 1. 頁面設定
st.set_page_config(page_title="戰情室", layout="wide", page_icon="🛡️")

# 2. 注入 CSS
st.markdown("""
    <style>
    div[data-testid="stFragment"] ::-webkit-scrollbar { display: none !important; width: 0px !important; }
    div[data-testid="stFragment"] { scrollbar-width: none !important; overflow: hidden !important; animation: none !important; transition: none !important; opacity: 1 !important; }
    div[class*="stShim"] { display: none !important; }
    div[data-testid="stPlotlyChart"] { background-color: #0E1117 !important; }
    iframe { background-color: #0E1117 !important; }
    .block-container { padding-top: 0.1rem !important; }
    header { visibility: hidden !important; } 
    div[data-testid="stTextInput"] { margin-bottom: 0px !important; }
    div[data-testid="stSelectbox"] { margin-bottom: 0px !important; }
    div[data-testid="stCheckbox"] { margin-top: 5px !important; }
    </style>
""", unsafe_allow_html=True)

# 3. Session State
if 'target_symbol' not in st.session_state: st.session_state['target_symbol'] = "2330.TW"
if 'input_field' not in st.session_state: st.session_state['input_field'] = "2330"
if 'pending_restart' not in st.session_state: st.session_state['pending_restart'] = False
if 'scan_results' not in st.session_state: st.session_state['scan_results'] = []
if 'sentiment_cache' not in st.session_state: st.session_state['sentiment_cache'] = {}

# 4. Secrets 自動讀取
FUGLE_KEY = st.secrets.get("FUGLE_KEY", None)
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", None)

is_key_loaded = (FUGLE_KEY is not None)
is_ai_ready = (GEMINI_API_KEY is not None)

# 5. Helper Functions
def reset_monitor():
    if st.session_state.get('auto_refresh_state'): 
        st.session_state['auto_refresh_state'] = False 
        st.session_state['pending_restart'] = True    

# 🚀 自動查詢中文名稱
def get_stock_code(user_input):
    s = str(user_input).strip().upper()
    raw_code = s.replace('.TW', '')
    
    # 情況 1: 輸入的是代號 (如 2330)
    if raw_code.isdigit():
        if raw_code in twstock.codes:
            return f"{raw_code}.TW", twstock.codes[raw_code].name
        return f"{raw_code}.TW", raw_code 
    
    # 情況 2: 輸入的是中文名稱 (如 台積電)
    for code, info in twstock.codes.items():
        if info.name == s:
            return f"{code}.TW", info.name
    
    return None, None

def update_symbol(symbol):
    st.session_state['target_symbol'] = symbol
    st.session_state['input_field'] = symbol.split('.')[0]
    reset_monitor()

# 🔥 AI 分析函式
def run_sentiment_analysis_debug(stock_code):
    if not HAS_HEAT_MODULE: 
        st.error(f"❌ 模組匯入失敗: {HEAT_ERROR}")
        return None
    
    try:
        results = asyncio.run(heat.run_analysis(stock_code.split('.')[0]))
        all_news = []
        for res in results:
            if isinstance(res, list): all_news.extend(res)
            
        st.toast(f"📰 抓到 {len(all_news)} 則新聞")
        
        if len(all_news) == 0:
            st.warning("⚠️ 沒抓到新聞，無法進行 AI 分析")
            return None

        score = None
        if is_ai_ready:
            st.toast("🧠 AI 正在閱讀新聞並進行戰略分析...")
            ai_score, ai_report, model = heat.analyze_with_gemini_requests(GEMINI_API_KEY, stock_code, all_news)
            
            if ai_score is not None:
                score = ai_score
                st.toast(f"✅ AI 分析完成！分數: {score}")
            else:
                st.error(f"❌ AI 分析失敗: {ai_report}")
                return None
        else:
            st.warning("⚠️ 未設定 Gemini Key，無法分析")
            return None
            
        st.session_state['sentiment_cache'][stock_code] = score
        return score

    except Exception as e:
        st.error(f"❌ 執行錯誤: {str(e)}")
        return None

# 重啟邏輯
if st.session_state['pending_restart']:
    with st.spinner("⏳ 重置中..."):
        time.sleep(0.5) 
        st.session_state['pending_restart'] = False 
        st.session_state['auto_refresh_state'] = True 
        st.rerun()

# --- 控制列 ---
c1, c2, c3 = st.columns([1.2, 0.8, 1])
with c1:
    user_input_val = st.text_input("代號", key="input_field", on_change=reset_monitor, label_visibility="collapsed", placeholder="股票代號")
with c2:
    timeframe_map = {"1分": "1T", "5分": "5T", "15分": "15T", "30分": "30T", "60分": "60T"}
    selected_tf_label = st.selectbox("週期", list(timeframe_map.keys()), index=0, on_change=reset_monitor, label_visibility="collapsed")
    selected_tf_code = timeframe_map[selected_tf_label]
with c3:
    auto_refresh = st.toggle("監控", value=False, key="auto_refresh_state")

if user_input_val:
    code, name = get_stock_code(user_input_val)
    if code and code != st.session_state['target_symbol']:
        st.session_state['target_symbol'] = code

resolved_code, resolved_name = get_stock_code(st.session_state['target_symbol'])
current_sentiment = st.session_state['sentiment_cache'].get(resolved_code, None)

# 8. Fragment 儀表板 (手機滑動優化版)
@st.fragment(run_every=5 if auto_refresh else None)
def display_dashboard():
    if not resolved_code: return

    with st.container(height=650, border=False):
        temp_score = current_sentiment if current_sentiment is not None else 50
        
        df, stats = get_orb_signals(
            resolved_code, 
            FUGLE_KEY, 
            timeframe=selected_tf_code,
            sentiment_score=temp_score
        )
        
        if df is not None:
            if current_sentiment is None:
                stats['entry_time'] = None
                stats['exit_time'] = None
                stats['signal'] = "等待 AI 指揮..."
                stats['strategy_name'] = "尚未啟動戰略"
                sentiment_display = "未分析"
                sentiment_color = "#757575"
                strat_color = "#757575"
            else:
                sentiment_display = str(current_sentiment)
                sentiment_color = "#FF5252" if current_sentiment > 60 else ("#00E676" if current_sentiment < 40 else "#888")
                strat_color = "#FFD700" if "接刀" in stats['strategy_name'] else "#00BFFF"

            current_price = stats['signal_price']
            last_vwap = df['VWAP'].iloc[-1] if not df.empty and 'VWAP' in df.columns else 0
            price_color = "#FF5252" if current_price > last_vwap else "#00E676"
            pct_change = stats.get('pct_change', 0) * 100
            
            # HUD (含中文名稱)
            hud_html = f"""
            <div style="display: flex; justify-content: space-between; align-items: center; background-color: #262730; padding: 10px 15px; border-radius: 8px; border: 1px solid #444; margin-bottom: 10px;">
                <div style="display: flex; flex-direction: column;">
                    <div style="display: flex; align-items: baseline; gap: 10px;">
                        <span style="font-size: 1.5rem; font-weight: bold; color: #FFF;">{resolved_name} <span style="font-size: 1rem; color: #AAA;">{resolved_code}</span></span>
                        <span style="font-size: 1.8rem; font-weight: bold; color: {price_color};">{current_price:.2f}</span>
                        <span style="font-size: 1rem; color: {price_color};">({pct_change:+.2f}%)</span>
                    </div>
                    <div style="font-size: 0.9rem; color: #AAA; margin-top: 5px;">
                        AI 情緒: <span style="color: {sentiment_color}; font-weight:bold; font-size: 1.1rem;">{sentiment_display}</span> 
                        <span style="margin: 0 5px;">|</span>
                        戰略: <span style="color: {strat_color}; font-weight:bold;">{stats['strategy_name']}</span>
                    </div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 0.8rem; color: #CCC;">VWAP <span style="color: yellow; font-weight: bold;">{last_vwap:.2f}</span></div>
                    <div style="font-size: 0.9rem; color: #888; margin-top: 5px;">{stats['signal']}</div>
                </div>
            </div>
            """
            st.markdown(hud_html, unsafe_allow_html=True)

            # --- 🔥 手機優化：圖表觸控鎖定開關 ---
            # 預設關閉 (False)，讓圖表變成靜態圖片，方便手機滑動
            c_tog, c_blank = st.columns([0.6, 0.4])
            with c_tog:
                enable_touch = st.toggle("🖐️ 解鎖圖表 (縮放/移動)", value=False)

            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="價格"))
            
            if 'vwap_data' in stats:
                fig.add_trace(go.Scatter(x=df.index, y=stats['vwap_data'], mode='lines', line=dict(color='yellow', width=2), name="VWAP"))
            
            if stats.get('entry_time'):
                fig.add_trace(go.Scatter(x=[stats['entry_time']], y=[stats['entry_price']], mode='markers', marker=dict(size=15, color='#FFD700', symbol='circle'), name="買進訊號"))
            if stats.get('exit_time'):
                 fig.add_trace(go.Scatter(x=[stats['exit_time']], y=[stats['exit_price']], mode='markers', marker=dict(size=15, color='#FF5252', symbol='x', line=dict(width=2, color='white')), name="出場訊號"))

            fig.update_layout(
                height=450, 
                template="plotly_dark", 
                plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', font=dict(color='white'),
                xaxis=dict(showgrid=True, gridcolor='#333', type='category'),
                yaxis=dict(showgrid=True, gridcolor='#333'),
                margin=dict(l=0, r=0, t=10, b=0), 
                uirevision=resolved_code, 
                transition={'duration': 0},
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10), bgcolor="rgba(0,0,0,0)")
            )
            
            # 🔥 關鍵設定：根據開關決定是否鎖定圖表
            chart_config = {
                'displayModeBar': False, 
                'staticPlot': not enable_touch,  # 沒開鎖前，圖表是靜態的(可滑動網頁)
                'scrollZoom': enable_touch
            }
            
            st.plotly_chart(fig, use_container_width=True, key="live_chart_fragment", config=chart_config)
        else:
            st.error("無法取得數據，請檢查代號或網路連線")

if resolved_code:
    display_dashboard()
    
    c_btn1, c_btn2 = st.columns([1, 1])
    with c_btn1:
        if current_sentiment is None:
            btn_text = f"🚀 啟動 {resolved_name} ({resolved_code}) AI 分析"
            btn_type = "primary"
        else:
            btn_text = f"🧠 重新分析 {resolved_name} (目前: {current_sentiment}分)"
            btn_type = "secondary"
            
        if st.button(btn_text, type=btn_type, use_container_width=True):
            if resolved_code:
                with st.spinner("🚀 AI 指揮官正在分析戰場情報 (約 10 秒)..."):
                    s = run_sentiment_analysis_debug(resolved_code)
                    if s is not None:
                        st.success(f"分析完成！戰略已更新。")
                        time.sleep(1)
                        st.rerun()
            else:
                st.error("請先輸入代號")
    with c_btn2:
        if st.button("🔥 全市場熱度掃描", use_container_width=True):
            st.session_state['scan_results'] = screen_hot_stocks(limit=15)
else:
    st.info("👈 請在上方輸入股票代號開始")

# --- 底部狀態檢查 ---
with st.expander("🛠️ 系統狀態檢查"):
    if is_key_loaded: st.success("✅ FUGLE_KEY: 連線正常")
    else: st.error("❌ FUGLE_KEY: 未設定")
    if is_ai_ready: st.success("✅ GEMINI_API_KEY: 連線正常")
    else: st.error("❌ GEMINI_API_KEY: 未設定")
    if HAS_HEAT_MODULE: st.success("✅ 爬蟲模組: 運作中")
    else: st.error(f"❌ 爬蟲模組: 故障. {HEAT_ERROR}")

if st.session_state['scan_results']:
    st.divider()
    st.markdown("##### 🔥 熱門潛力股掃描")
    for item in st.session_state['scan_results']:
        c1, c2, c3 = st.columns([2, 2, 1])
        c1.write(f"**{item['symbol']}**")
        c2.write(f"波動: {item['volatility']:.1f}%")
        target = item['symbol'].split('.')[0]
        c3.button("查看", key=f"btn_{item['symbol']}", on_click=update_symbol, args=(f"{target}.TW",))