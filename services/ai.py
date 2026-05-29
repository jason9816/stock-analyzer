import requests

from config import CLAUDE_PROXY_URL, GEMINI_API_KEYS, GEMINI_MODEL
from data.provider import get_info


def _call_gemini_raw(prompt, max_tokens=2048, temperature=0.3, model=None, tools=None):
    """底層 Gemini API 呼叫，支援 key rotation"""
    model = model or GEMINI_MODEL
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if tools:
        body["tools"] = tools

    last_err = None
    for key in GEMINI_API_KEYS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        try:
            resp = requests.post(url, json=body, timeout=60)
            result = resp.json()
            if 'candidates' in result:
                parts = result['candidates'][0]['content']['parts']
                return ''.join(p.get('text', '') for p in parts if not p.get('thought'))
            err_code = result.get('error', {}).get('code', 0)
            err_msg = result.get('error', {}).get('message', '')
            if err_code == 429:
                last_err = err_msg
                continue  # 換下一把 key
            raise Exception(err_msg[:200])
        except requests.exceptions.Timeout:
            last_err = 'API timeout'
            continue
    raise Exception(f'所有 API key 都被限流: {(last_err or "")[:100]}')


def call_gemini(prompt, max_tokens=2048, temperature=0.3):
    """呼叫 Gemini API，回傳生成的文字"""
    return _call_gemini_raw(prompt, max_tokens=max_tokens, temperature=temperature)


def call_gemini_with_search(prompt, max_tokens=4096, temperature=0.3):
    """呼叫 Gemini API + Google Search grounding，可搜尋最新資料

    嘗試順序：
    1. 預設 model + search grounding
    2. gemini-3.5-flash + search grounding
    3. gemini-3.5-flash 不帶 search（fallback）
    """
    models_to_try = [GEMINI_MODEL, 'gemini-3.5-flash']
    # 去重
    seen = set()
    models_to_try = [m for m in models_to_try if m not in seen and not seen.add(m)]

    last_err = None
    for model in models_to_try:
        try:
            return _call_gemini_raw(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
                tools=[{"google_search": {}}],
            )
        except Exception as e:
            last_err = str(e)
            continue

    # 全部帶 search 都失敗，用 gemini-3.5-flash 不帶 search
    try:
        return _call_gemini_raw(
            prompt, max_tokens=max_tokens, temperature=temperature, model='gemini-3.5-flash'
        )
    except Exception as e:
        raise Exception(f'研究 API 全部失敗: {last_err} / {e}')


def call_claude(prompt, max_tokens=300):
    """呼叫本地 Claude API proxy，回傳生成的文字"""
    resp = requests.post(
        f'{CLAUDE_PROXY_URL}/v1/messages',
        headers={
            'Content-Type': 'application/json',
            'x-api-key': 'dummy',
            'anthropic-version': '2023-06-01',
        },
        json={
            'model': 'claude-opus-4.6',
            'max_tokens': max_tokens,
            'messages': [{'role': 'user', 'content': prompt}],
        },
        timeout=30,
    )
    result = resp.json()
    if result.get('content'):
        return result['content'][0].get('text', '').strip()
    return None


def classify_stock(symbol):
    """
    Use Gemini to classify a stock and generate description.
    Returns: {'category': '半導體', 'tags': ['AI晶片', 'GPU'], 'description': 'AI GPU 龍頭...'}
    """
    import json

    name = symbol
    sector = ''
    industry = ''
    try:
        info = get_info(symbol)
        name = info.get('longName', info.get('shortName', symbol))
        sector = info.get('sector', '')
        industry = info.get('industry', '')
        summary = (info.get('longBusinessSummary', '') or '')[:500]
    except Exception:
        summary = ''

    try:
        prompt = f"""你是股票分類專家。根據以下資訊，用繁體中文回覆 JSON 格式：

股票代號: {symbol}
公司名稱: {name}
Sector: {sector}
Industry: {industry}
公司簡介: {summary}

請回覆以下 JSON（不要加 markdown 格式）：
{{"category": "主分類（如：半導體、軟體、金融、能源、REIT、生技、消費等）",
"tags": ["標籤1", "標籤2"],
"description": "一句話描述（20字以內，說明公司核心業務，像是 'AI GPU 龍頭，資料中心/遊戲/自駕車晶片'）"}}"""

        text = call_gemini(prompt, max_tokens=256, temperature=0.1)
        # Parse JSON from response
        # Try to extract JSON from potential markdown wrapping
        text = text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        result = json.loads(text)
        return result
    except Exception:
        # Fallback: use Yahoo Finance sector/industry
        try:
            return {
                'category': sector or '未分類',
                'tags': [industry] if industry else [],
                'description': f'{name} — {industry}' if industry else name,
            }
        except Exception:
            return {'category': '未分類', 'tags': [], 'description': symbol}
