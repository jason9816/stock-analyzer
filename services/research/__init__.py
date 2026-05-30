"""
題材研究 —— 掃熱門題材 + 對題材做深度研究（可抽換 provider）。

研究後端可抽換（跟 services/tunnel 同樣的 provider 模式）：
  research(topic) 依 config.RESEARCH_PROVIDER 分派到對應 provider。
  目前內建 'agy'（agy CLI）。要換 Gemini/Claude/自寫，照
  `research(topic) -> (text, candidates)` 介面新增函式並註冊到 _PROVIDERS。

公開 API：
  scan_themes()        掃多來源新聞 → 熱門題材清單
  research(topic)      對題材做深度研究 → (報告文字, candidates)
"""

from config import RESEARCH_PROVIDER
from services.research import agy
from services.research.themes import scan_themes

# provider 名稱 → research 函式
_PROVIDERS = {
    'agy': agy.research,
}


def research(topic: str) -> tuple:
    """依設定的 provider 對 topic 做深度研究，回傳 (報告文字, candidates list)。"""
    provider = _PROVIDERS.get(RESEARCH_PROVIDER)
    if provider is None:
        return f'❌ 未知的 RESEARCH_PROVIDER：{RESEARCH_PROVIDER}', []
    return provider(topic)


def research_to_report(
    topic: str, group: str = 'research', headlines=None, send_telegram: bool = True
) -> dict:
    """研究一個題材 → 產 Markdown/SVG/PDF（並可傳 Telegram）。

    回傳 services.report.save_and_send_report 的結果 dict（含 md_path/pdf_path/sent）。
    """
    from services.report import save_and_send_report

    text, candidates = research(topic)
    return save_and_send_report(
        group=group,
        theme=topic,
        theme_analysis=text,
        candidates=candidates,
        headlines=headlines,
        send_telegram_pdf=send_telegram,
    )


def daily_report(group: str = 'research') -> dict:
    """每日流程：掃題材 → 研究最熱門的一個 → 產 PDF 並傳 Telegram。

    回傳 research_to_report 的結果 dict；無題材則回 {}。
    """
    themes = scan_themes()
    if not themes:
        return {}
    top_theme, meta = themes[0]
    return research_to_report(top_theme, group=group, headlines=meta.get('headlines'))


__all__ = ['scan_themes', 'research', 'research_to_report', 'daily_report']
