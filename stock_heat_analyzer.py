import streamlit as st
import asyncio
from playwright.async_api import async_playwright
import time
import random
import sys
import xml.etree.ElementTree as ET
import os
import subprocess
import re

# === 雲端環境專用：自動安裝 Chromium ===
try:
    subprocess.run(["playwright", "install", "chromium"], check=True)
except Exception:
    pass

# === Windows 系統修復 ===
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ===========================
# 1. 爬蟲核心 (V12.1 格式修正版)
# ===========================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]
def get_ua(): return random.choice(USER_AGENTS)

# --- 核心功能：智慧解析 (強制分離代號與名稱) ---
async def resolve_stock_info(user_input):
    """
    輸入: "南亞" 或 "1303"
    輸出: ("1303", "南亞塑膠") 的 Tuple
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=get_ua())
        page = await context.new_page()
        try:
            # 搜尋關鍵字加上 "股票"，提高準確度
            query = f"{user_input} 股票"
            await page.goto(f"https://www.google.com/search?q={query}", timeout=10000)
            
            title = await page.title()
            # Google 標題範例: "南亞塑膠工業 (1303) - Google 財經" 
            # 或 "台積電 (2330) - Google 財經"
            
            # 1. 先抓出 4 碼數字代號 (這是最關鍵的)
            code_match = re.search(r"\((\d{4})\)", title)
            
            # 如果標題裡沒括號，試試看有沒有單獨的 4 碼數字
            if not code_match:
                code_match = re.search(r"\b(\d{4})\b", title)

            if code_match:
                stock_code = code_match.group(1)
                
                # 2. 抓取名稱：取括號前面的所有文字
                if "(" in title:
                    raw_name = title.split('(')[0].strip()
                else:
                    # 如果沒括號，就把代號切掉，剩下的就是名字
                    raw_name = title.replace(stock_code, "").split("-")[0].strip()
                
                # 清理一下名稱中的雜訊
                clean_name = raw_name.replace("股票", "").replace("股價", "").strip()
                
                return stock_code, clean_name
            
            return None, None
        except:
            return None, None
        finally:
            await browser.close()

# --- 通用 RSS 抓取函式 ---
async def fetch_google_rss(stock_code, site_domain, source_name):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=get_ua())
        page = await context.new_page()
        try:
            rss_url = f"https://news.google.com/rss/search?q={stock_code}+site:{site_domain}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            response = await page.goto(rss_url, timeout=20000, wait_until="commit")
            xml_content = await response.text()
            root = ET.fromstring(xml_content)
            data = []
            for item in root.findall('.//item'):
                title = item.find('title').text
                clean = title.split(" - ")[0]
                if len(clean) > 6: data.append({"title": clean, "source": source_name})
            return data[:5]
        except: return []
        finally: await browser.close()

# --- 各大媒體爬蟲模組 ---
async def scrape_anue(stock_code):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=get_ua())
        page = await context.new_page()
        try:
            await page.goto(f"https://www.cnyes.com/search/news?q={stock_code}", timeout=15000, wait_until="commit")
            await page.wait_for_timeout(1500)
            titles = await page.locator('h3, h2').all_inner_texts()
            return [{"title": t, "source": "鉅亨網"} for t in titles if len(t) > 6][:5]
        except: return []
        finally: await browser.close()

async def scrape_yahoo(stock_code):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=get_ua())
        page = await context.new_page()
        try:
            await page.goto(f"https://tw.stock.yahoo.com/quote/{stock_code}.TW/news", timeout=20000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            titles = await page.locator('#YDC-Stream li h3').all_inner_texts()
            if not titles: titles = await page.locator('#YDC-Stream li a').all_inner_texts()
            return [{"title": t, "source": "Yahoo"} for t in titles if len(t) > 5 and "廣告" not in t][:5]
        except: return []
        finally: await browser.close()

# RSS 組
async def scrape_udn(c): return await fetch_google_rss(c, "money.udn.com", "經濟日報")
async def scrape_ltn(c): return await fetch_google_rss(c, "ec.ltn.com.tw", "自由財經")
async def scrape_ctee(c): return await fetch_google_rss(c, "ctee.com.tw", "工商時報")
async def scrape_chinatimes(c): return await fetch_google_rss(c, "chinatimes.com", "中時新聞")
async def scrape_ettoday(c): return await fetch_google_rss(c, "ettoday.net", "ETtoday")
async def scrape_tvbs(c): return await fetch_google_rss(c, "news.tvbs.com.tw", "TVBS新聞")
async def scrape_businesstoday(c): return await fetch_google_rss(c, "businesstoday.com.tw", "今周刊")
async def scrape_wealth(c): return await fetch_google_rss(c, "wealth.com.tw", "財訊")
async def scrape_storm(c): return await fetch_google_rss(c, "storm.mg", "風傳媒")

# 計分邏輯
def calculate_score(news_list, source_name):
    if not news_list: return 0, []
    positive = ["上漲", "飆", "創高", "買超", "強勢", "超預期", "取得", "超越", "利多", "成長", "收益", "噴", "漲停", "旺", "攻頂", "受惠", "看好", "翻紅", "驚艷", "AI", "擴產", "先進", "動能", "發威", "領先", "搶單", "季增", "年增", "樂觀", "回溫", "布局", "利潤", "大漲", "完勝"]
    negative = ["下跌", "賣", "砍", "觀望", "保守", "不如", "重挫", "外資賣", "縮減", "崩", "跌停", "疲軟", "利空", "修正", "調節", "延後", "衰退", "翻黑", "示警", "重殺", "不如預期", "裁員", "虧損", "大跌", "重挫", "隱憂"]
    score = 50; reasons = []
    for news in news_list:
        t = news['title']
        hit = False
        for w in positive: 
            if w in t: score += 12; reasons.append(w); hit = True
        for w in negative: 
            if w in t: score -= 12; reasons.append(w); hit = True
        if not hit and len(t) > 5: score += 2
    return max(0, min(100, score)), list(set(reasons))

async def run_analysis(stock_code):
    return await asyncio.gather(
        scrape_anue(stock_code), scrape_yahoo(stock_code), scrape_udn(stock_code),
        scrape_ltn(stock_code), scrape_ctee(stock_code), scrape_chinatimes(stock_code),
        scrape_ettoday(stock_code), scrape_tvbs(stock_code), scrape_businesstoday(stock_code),
        scrape_wealth(stock_code), scrape_storm(stock_code)
    )

# ===========================
# 3. Streamlit 介面 (V12.1)
# ===========================
st.set_page_config(page_title="V12.1 智慧股票熱度儀", page_icon="📈", layout="wide")
st.markdown("""<style>.source-tag { padding: 3px 6px; border-radius: 4px; font-size: 11px; margin-right: 5px; color: white; display: inline-block; }.news-row { margin-bottom: 8px; padding: 4px; border-bottom: 1px solid #333; font-size: 14px; }.stock-check { background-color: #262730; padding: 10px; border-radius: 5px; border: 1px solid #4b4b4b; text-align: center; margin-bottom: 15px; }.stock-name-text { font-size: 24px; font-weight: bold; color: #4CAF50; }</style>""", unsafe_allow_html=True)

st.title("📈 V12.1 股市全視角熱度儀 (精準解析版)")
st.markdown("輸入 **「股票代碼」** 或 **「公司名稱」** 皆可，括號內自動顯示代碼。")

with st.sidebar:
    st.header("⚙️ 搜尋設定")
    user_input = st.text_input("輸入代碼或名稱 (按 Enter 確認)", value="2330")
    
    # === 智慧解析邏輯 ===
    if user_input:
        if 'last_input' not in st.session_state or st.session_state.last_input != user_input:
            with st.spinner(f"正在智慧搜尋 '{user_input}' 對應的代碼..."):
                code, name = asyncio.run(resolve_stock_info(user_input))
                if code:
                    st.session_state.target_code = code
                    st.session_state.target_name = name
                    st.session_state.last_input = user_input
                else:
                    st.session_state.target_code = None
                    st.session_state.target_name = None

        # === 顯示解析結果 (這裡修正了格式) ===
        if st.session_state.get('target_code'):
            name_display = st.session_state.target_name # 這裡是中文名稱
            code_display = st.session_state.target_code # 這裡是數字代號
            
            st.markdown(f"""
            <div class='stock-check'>
                <div style='font-size: 12px; color: #aaa;'>確認目標</div>
                <div class='stock-name-text'>{name_display}</div>
                <div style='font-size: 18px; color: #ccc; font-weight:bold; margin-top:5px;'>({code_display})</div>
            </div>
            """, unsafe_allow_html=True)
        else:
             st.markdown(f"<div class='stock-check' style='color:#ff4757'>⚠️ 找不到相關股票<br><small>請嘗試輸入更精確的名稱</small></div>", unsafe_allow_html=True)
    
    run_btn = st.button("🚀 啟動 11 核心掃描", type="primary", disabled=not st.session_state.get('target_code'))

# 主執行區
if run_btn:
    target_code = st.session_state.get('target_code')
    target_name = st.session_state.get('target_name')
    
    status = st.empty(); bar = st.progress(0)
    status.text(f"🔍 正在掃描 {target_name} ({target_code}) 的全網輿情...")
    bar.progress(10)
    
    # 這裡把 "代號" 傳給爬蟲，而不是傳名字
    results = asyncio.run(run_analysis(target_code))
    bar.progress(85)
    status.text("🧠 正在計算情緒權重...")
    
    source_names = ["鉅亨網", "Yahoo", "經濟日報", "自由財經", "工商時報", "中時新聞", "ETtoday", "TVBS新聞", "今周刊", "財訊", "風傳媒"]
    data_map = {name: res for name, res in zip(source_names, results)}
    
    scores = {}; all_signals = []; all_news = []; valid_count = 0; total_score = 0
    for name, data in data_map.items():
        s, r = calculate_score(data, name)
        scores[name] = s; all_signals.extend(r); all_news.extend(data)
        if len(data) > 0: total_score += s; valid_count += 1
    
    final_score = round(total_score / valid_count, 1) if valid_count > 0 else 0
    bar.progress(100); time.sleep(0.5); status.empty(); bar.empty()

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1: st.metric("全市場熱度", f"{final_score} 分", f"{len(all_news)} 則新聞")
    with col2:
        if final_score >= 75: l, c = "🔥🔥🔥 沸騰", "#ff4757"
        elif final_score >= 60: l, c = "🔥 加溫", "#ffa502"
        elif final_score <= 35: l, c = "🧊 冰凍", "#5352ed"
        else: l, c = "⚖️ 溫和", "#747d8c"
        st.markdown(f"<h2 style='color:{c}'>{l}</h2>", unsafe_allow_html=True)
    with col3: st.write(", ".join(list(set(all_signals))[:15]) if all_signals else "無訊號")
    
    st.divider()
    c1, c2 = st.columns(2)
    keys = list(data_map.keys())
    with c1:
        for name in keys[:6]:
            s = scores[name]; cnt = len(data_map[name])
            if cnt: st.write(f"**{name}**: {s}"); st.progress(s)
            else: st.caption(f"{name}: ⚠️")
    with c2:
        for name in keys[6:]:
            s = scores[name]; cnt = len(data_map[name])
            if cnt: st.write(f"**{name}**: {s}"); st.progress(s)
            else: st.caption(f"{name}: ⚠️")
            
    st.divider()
    if all_news:
        cmap = {"鉅亨網": "#0984e3", "Yahoo": "#6c5ce7", "經濟日報": "#e17055", "自由財經": "#d63031", "工商時報": "#00b894", "中時新聞": "#e84393", "ETtoday": "#fdcb6e", "TVBS新聞": "#2d3436", "今周刊": "#00cec9", "財訊": "#fab1a0", "風傳媒": "#636e72"}
        for n in all_news[:30]:
            bg = cmap.get(n['source'], "#999")
            st.markdown(f"<div class='news-row'><span class='source-tag' style='background-color:{bg}'>{n['source']}</span><a href='https://www.google.com/search?q={n['title']}' target='_blank' style='text-decoration:none; color:inherit'>{n['title']}</a></div>", unsafe_allow_html=True)
    else: st.info("無新聞")