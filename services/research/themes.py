"""
熱門題材掃描 —— 多來源新聞 + Gemini 歸納出可選股的投資題材。

來源：yfinance 個股新聞、Google News RSS、Finviz。
回傳：[(theme_name, {count, headlines, why}), ...]
"""

import json
import re

import requests

from services.ai import call_gemini

_SCAN_TICKERS = [
    'SPY',
    'QQQ',
    'DIA',
    'SOXX',
    'XLK',
    'XLE',
    'XLV',
    'ARKK',
    'TAN',
    'LIT',
    'HACK',
    'ROBO',
    'UFO',
    'NVDA',
    'AAPL',
    'MSFT',
    'GOOGL',
    'TSLA',
    'AMD',
    'AVGO',
    'SMCI',
    'ARM',
]

_GOOGLE_FEEDS = [
    'https://news.google.com/rss/search?q=stock+market+investing&hl=en&gl=US',
    'https://news.google.com/rss/search?q=AI+semiconductor+data+center&hl=en&gl=US',
    'https://news.google.com/rss/search?q=space+satellite+technology&hl=en&gl=US',
    'https://news.google.com/rss/search?q=energy+nuclear+renewable&hl=en&gl=US',
]


def _fetch_google_news() -> list:
    import xml.etree.ElementTree as ET

    articles = []
    for feed_url in _GOOGLE_FEEDS:
        try:
            r = requests.get(feed_url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
            root = ET.fromstring(r.text)
            for item in root.findall('.//item')[:8]:
                title = item.findtext('title', '')
                desc = item.findtext('description', '')
                if title:
                    desc_clean = re.sub(r'<[^>]+>', '', desc)[:200] if desc else ''
                    articles.append(f'{title}. {desc_clean}'.strip())
        except Exception:
            continue
    return articles


def _fetch_finviz_news() -> list:
    try:
        r = requests.get(
            'https://finviz.com/news.ashx', timeout=8, headers={'User-Agent': 'Mozilla/5.0'}
        )
        return re.findall(r'class="nn-tab-link"[^>]*>([^<]+)</a>', r.text)[:20]
    except Exception:
        return []


def _gather_articles() -> list:
    import yfinance as yf

    articles = []
    for ticker in _SCAN_TICKERS:
        try:
            for n in (yf.Ticker(ticker).news or [])[:2]:
                c = n.get('content', {})
                title = c.get('title', '')
                if not title:
                    continue
                summary = re.sub(r'<[^>]+>', '', c.get('summary', ''))[:200]
                entry = f'[{ticker}] {title}' + (f' — {summary}' if summary else '')
                if entry not in articles:
                    articles.append(entry)
        except Exception:
            continue
    for a in _fetch_google_news():
        if a not in articles:
            articles.append(f'[GoogleNews] {a}')
    for a in _fetch_finviz_news():
        if a not in articles:
            articles.append(f'[Finviz] {a}')
    return articles


def scan_themes() -> list:
    """掃描多來源新聞，用 Gemini 歸納出 5-8 個可選股的熱門題材。"""
    articles = _gather_articles()
    if not articles:
        return []

    articles_text = '\n'.join(f'- {a}' for a in articles[:80])
    prompt = f"""你是投資題材分析師。從以下財經新聞標題中，找出目前最熱門的投資題材。

新聞（共 {len(articles[:80])} 則，來自 Yahoo Finance、Google News、Finviz）：
{articles_text}

請歸納出 5-8 個最熱門的投資題材。規則：
1. 題材必須從新聞內容歸納，不是自己編的
2. 題材要具體到可搜尋相關供應鏈股票（「AI 液冷散熱供應鏈」比「科技」好）
3. 排除大盤走勢、總經（升降息）等無法選股的題材
4. 優先「正在發生變化」的題材（新技術、產能瓶頸、政策變化）

只用 JSON 回答：
[{{"theme": "題材名稱", "count": 相關新聞數, "headline": "代表標題", "why": "為什麼熱門（一句）"}}]"""

    try:
        result = call_gemini(prompt, max_tokens=1024, temperature=0.1)
        match = re.search(r'\[.*\]', result, re.DOTALL)
        if not match:
            return []
        themes = []
        for t in json.loads(match.group()):
            name = t.get('theme', '')
            if name:
                themes.append(
                    (
                        name,
                        {
                            'count': t.get('count', 1),
                            'headlines': [t['headline']] if t.get('headline') else [],
                            'why': t.get('why', ''),
                        },
                    )
                )
        return themes[:8]
    except Exception as e:
        print(f'⚠️ 題材掃描失敗：{e}')
        return []
