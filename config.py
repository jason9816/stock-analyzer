"""
全域設定 — 密鑰一律從 .env 讀取（見 .env.example）。
非敏感的程式設定（模型名、股票池、槓桿表）直接寫在這裡。
"""

import os
import shutil

try:
    from dotenv import load_dotenv

    load_dotenv()  # 載入專案根目錄的 .env
except ImportError:
    pass  # 未裝 python-dotenv 時，仍可從系統環境變數讀取


def _env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_list(name, default=None):
    """逗號分隔的環境變數 → list（去空白、去空項）"""
    val = os.environ.get(name, '')
    items = [x.strip() for x in val.split(',') if x.strip()]
    return items or (default or [])


# ── 密鑰（從 .env 讀取，無預設值）────────────────────────
GEMINI_API_KEYS = _env_list('GEMINI_API_KEYS')
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ''
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.5-flash')

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

ALPACA_PAPER_KEY = os.environ.get('ALPACA_PAPER_KEY', '')
ALPACA_PAPER_SECRET = os.environ.get('ALPACA_PAPER_SECRET', '')

WEB_PASSWORD = os.environ.get('WEB_PASSWORD', '')
CLAUDE_PROXY_URL = os.environ.get('CLAUDE_PROXY_URL', 'http://localhost:4141')

# 外部工具路徑（Windows 友善：預設靠 PATH 自動尋找）
MD_TO_PDF_PATH = os.environ.get('MD_TO_PDF_PATH') or shutil.which('md-to-pdf') or 'md-to-pdf'
AGY_PATH = os.environ.get('AGY_PATH') or shutil.which('agy') or 'agy'

# ── 題材研究後端（可抽換：agy / …）──────────────────────
RESEARCH_PROVIDER = os.environ.get('RESEARCH_PROVIDER', 'agy').strip().lower()

# ── 對外導出（可抽換：none / ngrok）──────────────────────
TUNNEL_PROVIDER = os.environ.get('TUNNEL_PROVIDER', 'none').strip().lower()
# 可填多把 token（逗號分隔），第一把流量爆了會自動切下一把
NGROK_AUTHTOKENS = _env_list('NGROK_AUTHTOKENS') or _env_list('NGROK_AUTHTOKEN')
NGROK_AUTHTOKEN = NGROK_AUTHTOKENS[0] if NGROK_AUTHTOKENS else ''
# 對應的固定 dev domain（順序與 NGROK_AUTHTOKENS 相同；某把沒設就用隨機網址）
NGROK_DOMAINS = _env_list('NGROK_DOMAINS')

# ── 功能開關（從 .env 讀，預設值寫在這裡）────────────────
FEATURE_FLAGS = {
    'US_MARKET': _env_bool('ENABLE_US_MARKET', True),
    'TW_MARKET': _env_bool('ENABLE_TW_MARKET', True),
    'AI_ANALYSIS': _env_bool('ENABLE_AI_ANALYSIS', True),  # 需 GEMINI_API_KEYS
    'TRADING': _env_bool('ENABLE_TRADING', False),  # 需 Alpaca key
    'STRATEGY': _env_bool('ENABLE_STRATEGY', False),
    'THEME_RESEARCH': _env_bool(
        'ENABLE_THEME_RESEARCH', False
    ),  # 題材掃描+研究+PDF（需 agy / Gemini）
    'AI_CHAT': _env_bool('ENABLE_AI_CHAT', False),  # /chat 問答（密碼保護，需 GEMINI_API_KEYS）
    'TELEGRAM_BOT': _env_bool('ENABLE_TELEGRAM_BOT', False),  # 需 Telegram token
    'BG_WORKERS': _env_bool('ENABLE_BG_WORKERS', True),
}

WEB_PORT = int(os.environ.get('WEB_PORT', '5000'))

# ── 持久化儲存 ──────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock_data.json')
DEFAULT_STOCKS = ['NVDA', 'TSLA', 'GOOGL']
