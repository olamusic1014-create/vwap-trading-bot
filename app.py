import streamlit as st
from PIL import Image  # 新增這個：用來讀取圖片
import streamlit.components.v1 as components
import plotly.graph_objects as go
import pandas as pd
import time
import analyzer
from analyzer import get_orb_signals, screen_hot_stocks, backtest_past_week
import twstock

# --- 設定頁面圖示 (修正版) ---
# 請確保資料夾內有一張名為 "icon.png" 的圖片
# 如果你的圖片檔名不一樣，請修改下面括號裡的檔名
try:
    icon_img = Image.open("icon.png") 
    st.set_page_config(
        page_title="智能選股戰情室", 
        layout="wide",
        page_icon=icon_img  # 使用圖片檔案作為圖示
    )
except FileNotFoundError:
    # 萬一找不到圖片，會自動退回使用 Emoji，避免程式崩潰
    st.set_page_config(
        page_title="智能選股戰情室", 
        layout="wide",
        page_icon="🤖"
    )

if 'target_symbol' not in st.session_state: st.session_state['target_symbol'] = "2301"
if 'backtest_results' not in st.session_state: st.session_state['backtest_results'] = None
if 'history_results' not in st.session_state: st.session_state['history_results'] = None
if 'scroll_to_top' not in st.session_state: st.session_state['scroll_to_top'] = False
if 'input_field' not in st.session_state: st.session_state['input_field'] = "2301"

if st.session_state['scroll_to_top']:
    components.html("""<script>window.parent.document.querySelector('section.main').scrollTo(0, 0);</script>""", height=0)
    st.session_state['scroll_to_top'] = False

def get_stock_code(user_input):
    user_input = user_input.strip()
    if user_input.isdigit(): return f"{user_input}.TW", user_input
    for code, info in twstock.codes.items():
        if info.name == user_input: return f"{code}.TW", info.name
    return None, None

def update_symbol(symbol):
    st.session_state['target_symbol'] = symbol
    st.session_state['input_field'] = symbol 
    st.session_state['scroll_to_top'] = True

st.title("🛡️ VWAP 智能選股與回測系統 (高敏感度版)")

st.sidebar.header("參數設定")
user_input_val = st.sidebar.text_input("輸入股票代號", key="input_field")
auto_refresh = st.sidebar.checkbox("🔄 啟用即時監控", value=False)
run_btn = st.sidebar.button("開始分析 / 刷新")

st.sidebar.divider()
st.sidebar.subheader("進階功能")
c1, c2 = st.sidebar.columns(2)
run_history = c1.button("📅 單股歷史回測 (近5日)")
run_smart_scan = c2.button("🔥 全市場智能選股")

if user_input_val != st.session_state['target_symbol']:
    st.session_state['target_symbol'] = user_input_val

if run_history:
    target = st.session_state['target_symbol']
    if not target.endswith('.TW'): target += '.TW'
    with st.spinner(f"正在回測 {target} 過去 5 天的表現..."):
        hist_res = backtest_past_week(target)
        st.session_state['history_results'] = hist_res

if run_smart_scan:
    with st.spinner("正在掃描市場熱門股..."):
        top_candidates = screen_hot_stocks(limit=15)
        if top_candidates:
            scan_codes = [x['symbol'] for x in top_candidates]
            results = []
            bar = st.progress(0)
            for i, t in enumerate(scan_codes):
                res = analyzer.backtest_strategy(t)
                if res['status'] != 'ERROR': results.append(res)
                bar.progress((i+1)/len(scan_codes))
            st.session_state['backtest_results'] = results

resolved_code, resolved_name = get_stock_code(st.session_state['target_symbol'])

if not resolved_code:
    st.error("無效的股票代號")
else:
    # --- 歷史回測結果區塊 ---
    if st.session_state['history_results']:
        st.subheader(f"📅 {resolved_name} 近 5 日策略績效")
        df_hist = pd.DataFrame(st.session_state['history_results'])
        
        if not df_hist.empty:
            traded_days = df_hist[~df_hist['status'].isin(['NO_SIGNAL', 'SKIPPED'])]
            
            if not traded_days.empty:
                total_trades = len(traded_days)
                win_count = len(traded_days[traded_days['status'] == 'WIN'])
                win_rate = (win_count / total_trades * 100)
                total_pnl = traded_days['pnl'].sum()
                
                m1, m2, m3 = st.columns(3)
                m1.metric("有效交易天數", total_trades)
                m2.metric("週間勝率", f"{win_rate:.1f}%")
                m3.metric("週間總損益", f"{total_pnl:.2f}%", delta_color="normal")
                
                def highlight_row(row):
                    if row['status'] == 'WIN': 
                        return ['background-color: #198754; color: white'] * len(row)
                    if row['status'] == 'LOSS': 
                        return ['background-color: #DC3545; color: white'] * len(row)
                    return [''] * len(row)

                st.dataframe(
                    traded_days.style.apply(highlight_row, axis=1)
                    .format({'pnl': "{:.2f}%", 'entry': "{:.2f}", 'exit': "{:.2f}"})
                )
            else:
                st.info("過去 5 天無符合進場條件的交易 (NO_SIGNAL)。")
        else:
            st.info("無法取得足夠的歷史資料。")
        st.divider()

    # --- 即時圖表 ---
    df, stats = get_orb_signals(resolved_code)
    if df is not None:
        st.subheader(f"📊 {resolved_name} 當日走勢")
        live_tag = "🔴 LIVE" if stats.get('is_realtime') else "⚠️ DELAYED"
        st.caption(f"即時報價: {stats['signal_price']:.2f} ({live_tag})")
        
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="價格"))
        if 'vwap_data' in stats:
            fig.add_trace(go.Scatter(x=df.index, y=stats['vwap_data'], mode='lines', line=dict(color='yellow', width=2), name="VWAP"))
        
        if stats.get('entry_time'):
            fig.add_trace(go.Scatter(x=[stats['entry_time']], y=[stats['entry_price']], mode='markers', marker=dict(size=15, color='#FFD700'), name="買進"))
        
        # 🔥 修正出場標記顏色：紅色填充 + 白色邊框
        if stats.get('exit_time'):
            fig.add_trace(go.Scatter(
                x=[stats['exit_time']], 
                y=[stats['exit_price']], 
                mode='markers', 
                marker=dict(size=15, color='red', symbol='x', line=dict(width=2, color='white')), # 改這裡
                name="出場"
            ))

        # 🔥 修正圖表背景：強制使用深色背景
        fig.update_layout(
            height=450, 
            template="plotly_dark", 
            plot_bgcolor='#0E1117', # 圖表區域背景黑
            paper_bgcolor='#0E1117', # 畫布背景黑
            font=dict(color='white'), # 字體白
            xaxis=dict(showgrid=True, gridcolor='#333'), # 網格線深灰
            yaxis=dict(showgrid=True, gridcolor='#333'), 
            margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig, use_container_width=True)

# --- 智能選股列表 ---
if st.session_state['backtest_results']:
    st.divider()
    st.header("🔥 智能篩選結果 (僅顯示有效交易)")
    df_res = pd.DataFrame(st.session_state['backtest_results'])
    
    valid_trades = df_res[~df_res['status'].isin(['NO_SIGNAL', 'SKIPPED_LOW_VOL', 'SKIPPED'])]
    
    if not valid_trades.empty:
        total = len(valid_trades)
        wins = len(valid_trades[valid_trades['status'].str.contains('WIN')])
        win_rate = (wins / total) * 100
        avg_pnl = valid_trades['pnl'].mean()
        
        m1, m2, m3 = st.columns(3)
        m1.metric("有效交易次數", total)
        m2.metric("勝率", f"{win_rate:.1f}%")
        m3.metric("平均報酬", f"{avg_pnl:.2f}%")
        
        st.markdown("---")
        cols = st.columns([1.5, 2, 1.5, 1.5, 2, 1])
        cols[0].write("**代號**")
        cols[1].write("**狀態**")
        cols[2].write("**損益**")
        cols[3].write("**波動率**")
        cols[4].write("**訊號**")
        cols[5].write("**動作**")
        st.markdown("---")

        for index, row in valid_trades.iterrows():
            c1, c2, c3, c4, c5, c6 = st.columns([1.5, 2, 1.5, 1.5, 2, 1])
            c1.write(row['symbol'])
            
            status = row['status']
            color = "#00FF00" if "WIN" in status else "#FF4B4B"
            c2.markdown(f"<span style='color:{color}'>{status}</span>", unsafe_allow_html=True)
            c3.write(f"{row['pnl']:.2f}%")
            c4.write(f"{row.get('adr', 0):.2f}%")
            c5.write(row['signal_type'])
            
            target = row['symbol'].split('.')[0]
            c6.button("🔍", key=f"btn_{row['symbol']}", on_click=update_symbol, args=(target,))
    else:
        st.info("即使在寬鬆條件下，今日篩選的強勢股仍無進場訊號 (可能全數直接噴出無回檔)。")