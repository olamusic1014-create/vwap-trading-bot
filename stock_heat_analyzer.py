import asyncio
from playwright.async_api import async_playwright
import time
import random
import sys
import xml.etree.ElementTree as ET
import os
import subprocess
import re
from datetime import datetime, timedelta
import email.utils

# 自動安裝依賴
try:
    import requests
    import google.generativeai as genai
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "google-generativeai"], check=True)
    import requests
    import google.generativeai as genai

# 雲端環境安裝 Chromium
try:
    subprocess.run(["playwright", "install", "chromium"], check=True)
except Exception:
    pass

# Windows 系統修復
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]
def get_ua(): return random.choice(USER_AGENTS)

def is_within_3_days(date_obj):
    if not date_obj: return True
    if date_obj.tzinfo is not None: date_obj = date_obj.replace(tzinfo=None)
    return (datetime.now() - date_obj).days <= 3

# RSS 抓取
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
                link = item.find('link').text
                pub = item.find('pubDate').text
                is_fresh = True
                if pub:
                    try:
                        pd = email.utils.parsedate_to_datetime(pub)
                        if not is_within_3_days(pd): is_fresh = False
                    except: pass
                if is_fresh:
                    clean_title = title.split(" - ")[0]
                    if len(clean_title) > 4:
                        desc = item.find('description').text or ""
                        clean_desc = re.sub(r'<[^>]+>', '', desc)
                        data.append({"title": clean_title, "snippet": clean_desc[:200], "source": source_name, "link": link})
            return data[:3]
        except: return []
        finally: await browser.close()

# 媒體爬蟲
async def scrape_anue(stock_code):
    try:
        url = f"https://ess.api.cnyes.com/ess/api/v1/news/keyword?q={stock_code}&limit=10&page=1"
        res = requests.get(url, headers={"User-Agent": get_ua()}, timeout=5)
        if res.status_code == 200:
            items = res.json().get('data', {}).get('items', [])
            result = []
            limit_ts = int(time.time()) - (3 * 86400)
            for item in items:
                if item.get('publishAt', 0) >= limit_ts:
                    result.append({"title": item['title'], "snippet": item.get('summary', ''), "source": "鉅亨網", "link": f"https://news.cnyes.com/news/id/{item['newsId']}"})
            return result[:3]
    except: pass
    return []

async def scrape_yahoo(stock_code):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=get_ua())
        page = await context.new_page()
        try:
            await page.goto(f"https://tw.stock.yahoo.com/quote/{stock_code}.TW/news", timeout=20000)
            data = []
            els = await page.locator('#main-2-QuoteNews-Proxy a[href*="/news/"]').all()
            seen = set()
            for el in els[:3]:
                t = await el.inner_text()
                h = await el.get_attribute("href")
                title = max(t.split('\n'), key=len) if t else ""
                if len(title) > 5 and title not in seen:
                    seen.add(title)
                    data.append({"title": title, "snippet": "Yahoo 焦點", "source": "Yahoo", "link": h})
            return data
        except: return []
        finally: await browser.close()

# 整合執行
async def run_analysis(stock_code):
    tasks = [
        scrape_anue(stock_code), scrape_yahoo(stock_code),
        fetch_google_rss(stock_code, "money.udn.com", "經濟日報"),
        fetch_google_rss(stock_code, "ec.ltn.com.tw", "自由財經"),
        fetch_google_rss(stock_code, "ctee.com.tw", "工商時報")
    ]
    return await asyncio.gather(*tasks)

# 關鍵字備用評分
def calculate_score_keyword_fallback(news_list):
    if not news_list: return 50
    pos = ["上漲", "飆", "創高", "買超", "強勢", "利多", "成長", "漲停", "旺", "攻頂", "受惠", "看好", "翻紅", "驚艷", "AI", "擴產", "獲利", "大漲"]
    neg = ["下跌", "賣", "砍", "觀望", "保守", "重挫", "外資賣", "縮減", "崩", "跌停", "疲軟", "利空", "修正", "衰退", "翻黑", "示警", "虧損", "大跌"]
    score = 50
    for n in news_list:
        txt = n['title'] + str(n.get('snippet', ''))
        for w in pos: 
            if w in txt: score += 5
        for w in neg: 
            if w in txt: score -= 5
    return max(0, min(100, score))

# AI 評分 (🔥 官方套件版：最穩定的連線方式)
def analyze_with_gemini_requests(api_key, stock_name, news_data):
    txt = "\n".join([f"{i+1}. [{n['source']}] {n['title']}" for i, n in enumerate(news_data)])
    prompt = f"分析「{stock_name}」最新新聞情緒(0-100分)。新聞：\n{txt}\n\n格式：\nSCORE: [分數]\nSUMMARY: [簡短總結]"
    
    try:
        # 設定 API Key
        genai.configure(api_key=api_key)
        
        # 嘗試使用最新的 Flash 模型
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(prompt)
        except:
            # 如果失敗，回退到最穩定的 Pro 模型
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(prompt)
            
        content = response.text
        match = re.search(r"SCORE:\s*(\d+)", content)
        score = int(match.group(1)) if match else 50
        
        return score, content, model.model_name

    except Exception as e:
        return None, f"SDK Error: {str(e)}", "error"