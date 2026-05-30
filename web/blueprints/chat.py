"""
AI 問答 blueprint —— 密碼保護的唯讀對話，問 code 邏輯 / 資料邏輯 / 個股。

安全邊界：唯讀。只把「系統說明 + （若問題含代號）該股的即時分析」餵給 Gemini，
不讀任意檔、不執行任何指令、不寫入。密碼用既有的 WEB_PASSWORD。
"""

import os
import re

from flask import Blueprint, jsonify, render_template, request

from config import WEB_PASSWORD
from services.ai import call_gemini

bp = Blueprint('chat', __name__)

_INSTRUCTION = (
    '你是這個股票分析系統的助理，協助開發者理解程式與資料邏輯，並回答個股問題。'
    '下面是本專案的架構文件，請依它回答。用繁體中文、具體、誠實；'
    '不確定就說不確定，不要編造數字或來源。'
)
_ARCH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'ARCHITECTURE.md'
)


def _system_context() -> str:
    """系統脈絡＝指示 + ARCHITECTURE.md（單一來源，架構文件改了這裡自動同步）。"""
    try:
        with open(_ARCH_PATH, encoding='utf-8') as f:
            return f'{_INSTRUCTION}\n\n=== ARCHITECTURE.md ===\n{f.read()}'
    except OSError:
        return _INSTRUCTION


def _check_pwd(data) -> bool:
    return bool(WEB_PASSWORD) and data.get('pwd', '') == WEB_PASSWORD


def _maybe_stock_context(question: str) -> str:
    """問題若含股票代號，附上該股即時分析（best-effort，失敗就略過）。"""
    m = re.search(r'\b([A-Z]{1,5})\b', question)
    if not m:
        return ''
    try:
        from core.analysis import get_stock_analysis

        a = get_stock_analysis(m.group(1))
        sw = a.get('swing', {})
        mid = a.get('mid_trend', {})
        return (
            f"\n\n【{m.group(1)} 即時分析】價:{a.get('price')} "
            f"短線:{sw.get('signal')}({sw.get('score')}) "
            f"中線:{mid.get('label')}({mid.get('score')}) "
            f"籌碼:{a.get('chip_lbl')}({a.get('chip_score')}) 狀態:{a.get('status')}"
        )
    except Exception:
        return ''


@bp.route('/chat')
def chat_page():
    return render_template('chat.html')


@bp.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json() or {}
    if not _check_pwd(data):
        return jsonify({'error': '密碼錯誤'}), 403
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({'error': '請輸入問題'}), 400
    prompt = f"{_system_context()}{_maybe_stock_context(question)}\n\n使用者問題：{question}"
    try:
        answer = call_gemini(prompt, max_tokens=2048, temperature=0.3)
        return jsonify({'ok': True, 'answer': answer})
    except Exception as e:
        return jsonify({'error': f'AI 回覆失敗：{e}'}), 500
