"""AI 摘要 blueprint：個股新聞摘要、大盤環境摘要（Gemini）。"""

import re
from datetime import datetime

import pandas as pd
from flask import Blueprint, jsonify, request

from config import WEB_PASSWORD
from core.indicators import calc_macd, calc_rsi, get_dxy, get_market_vix, get_sp500, get_us10y
from data.provider import get_news, get_ticker
from data.store import get_watchlist, load_data, save_data
from services.ai import call_gemini

bp = Blueprint('ai_summary', __name__)


@bp.route('/api/news_summary')
def api_news_summary():
    """用 Gemini 統整單一股票的新聞 + 技術面"""
    market = request.args.get('market', 'us')
    sym = request.args.get('symbol', '').upper().strip()
    if request.args.get('pwd', '') != WEB_PASSWORD:
        return jsonify({'ok': False, 'error': '密碼錯誤'})
    if not sym:
        return jsonify({'ok': False, 'error': '缺少股票代號'})

    currency_sign = 'NT$' if market == 'tw' else '$'
    analyst_role = '台股分析師' if market == 'tw' else '美股分析師'

    try:
        t = get_ticker(sym)
        info = t.info
        cp = info.get('regularMarketPrice', 0)
        post = info.get('postMarketPrice')
        post_chg = info.get('postMarketChangePercent')
        pre = info.get('preMarketPrice')
        pre_chg = info.get('preMarketChangePercent')

        raw_news = t.news or []
        news_text = []
        for n in raw_news[:8]:
            c = n.get('content', {})
            title = c.get('title', '')
            summary = re.sub(r'<[^>]+>', '', c.get('summary', ''))[:250]
            provider = c.get('provider', {}).get('displayName', '')
            if title:
                news_text.append(f"- [{provider}] {title}: {summary}")

        hist = t.history(period="6mo")
        if len(hist) > 20:
            hist['RSI'] = calc_rsi(hist['Close'])
            ml, sl, mh = calc_macd(hist['Close'])
            rsi_val = round(hist['RSI'].iloc[-1], 1) if not pd.isna(hist['RSI'].iloc[-1]) else 'N/A'
            macd_cross = '金叉' if ml.iloc[-1] > sl.iloc[-1] else '死叉'
            macd_hist_val = round(mh.iloc[-1], 3)
            ma5 = hist['Close'].rolling(5).mean().iloc[-1]
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            ma60 = hist['Close'].rolling(60).mean().iloc[-1] if len(hist) >= 60 else None
            chg_5d = round((hist['Close'].iloc[-1] / hist['Close'].iloc[-5] - 1) * 100, 2)
            chg_20d = round((hist['Close'].iloc[-1] / hist['Close'].iloc[-20] - 1) * 100, 2)
            vol_ratio = (
                round(hist['Volume'].iloc[-5:].mean() / hist['Volume'].iloc[-20:].mean(), 2)
                if hist['Volume'].iloc[-20:].mean() > 0
                else 1
            )
            tech_text = (
                f"RSI={rsi_val}, MACD {macd_cross}(柱狀體={macd_hist_val}), "
                f"MA5={currency_sign}{ma5:.2f}, MA20={currency_sign}{ma20:.2f}, "
                + (f"MA60={currency_sign}{ma60:.2f}, " if ma60 else "")
                + f"5天漲跌={chg_5d:+.2f}%, 20天漲跌={chg_20d:+.2f}%, 量能比={vol_ratio}x"
            )
        else:
            tech_text = "資料不足"

        market_text = f"現價 {currency_sign}{cp:.2f}"
        if pre:
            market_text += f", 盤前 {currency_sign}{pre:.2f}({pre_chg:.2f}%)"
        elif post:
            market_text += f", 盤後 {currency_sign}{post:.2f}({post_chg:.2f}%)"

        prompt = f"""你是專業{analyst_role}，幫台灣散戶分析 {sym}。

要求：
1. 用繁體中文，簡潔有力
2. 先用 1-2 行統整新聞重點，標註【利多】【利空】【中性】
3. 結合技術面數據，給出「📌 操作建議」（買/賣/持有/觀望，具體理由）
4. 如果有重大風險（財報、訴訟、降評等）要特別標註 ⚠️
5. 總共不要超過 150 字

【{sym}】{market_text}
技術面：{tech_text}

最新新聞：
{chr(10).join(news_text) if news_text else '無最新新聞'}
"""

        text = call_gemini(prompt)
        data = load_data(market)
        data.setdefault('ai_analysis', {})[sym] = {
            'text': text,
            'timestamp': datetime.now().isoformat(),
        }
        save_data(data, market)
        return jsonify({'ok': True, 'summary': text, 'time': datetime.now().strftime('%H:%M')})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)[:100]})


@bp.route('/api/market_summary')
def api_market_summary():
    """用 Gemini 統整大盤環境：VIX、S&P、美債、DXY + 總體新聞"""
    if request.args.get('pwd', '') != WEB_PASSWORD:
        return jsonify({'ok': False, 'error': '密碼錯誤'})

    try:
        vix = get_market_vix()
        sp500, sp500_chg = get_sp500()
        dxy = get_dxy()
        us10y = get_us10y()

        news_text = []
        for etf_sym in ['SPY', 'QQQ', '^VIX']:
            try:
                raw = get_news(etf_sym) or []
                for n in raw[:4]:
                    c = n.get('content', {})
                    title = c.get('title', '')
                    summary = re.sub(r'<[^>]+>', '', c.get('summary', ''))[:200]
                    provider = c.get('provider', {}).get('displayName', '')
                    if title and title not in [x.split('] ')[-1].split(':')[0] for x in news_text]:
                        news_text.append(f"- [{provider}] {title}: {summary}")
            except Exception:
                pass

        watchlist = get_watchlist()

        prompt = f"""你是專業美股分析師，幫台灣散戶判斷今天的大盤環境。

要求：
1. 用繁體中文
2. 先統整今天的重大消息（川普政策、聯準會、關稅、地緣政治等），標註【利多】【利空】
3. 結合大盤指標判斷市場狀態
4. 最後用一句話回答：「🟢 適合進場」「🟡 觀望為主」「🔴 避免操作」
5. 如果有特定產業/板塊受影響，提一下
6. 不要超過 200 字

大盤指標：
- S&P 500: {sp500} ({sp500_chg:+.2f}%)
- VIX 恐慌指數: {vix}
- 美元指數 DXY: {dxy}
- 美 10 年期公債殖利率: {us10y}%

用戶追蹤的股票：{', '.join(watchlist)}

最新市場新聞：
{chr(10).join(news_text[:10]) if news_text else '無'}
"""

        text = call_gemini(prompt)
        data = load_data()
        data['market_ai'] = {'text': text, 'timestamp': datetime.now().isoformat()}
        save_data(data)
        return jsonify({'ok': True, 'summary': text, 'time': datetime.now().strftime('%H:%M')})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)[:100]})
