#!/usr/bin/env python3
"""
Telegram 互動 bot 範本 —— 一個可擴充的指令骨架。

這是給 clone 者照抄的樣板：示範如何輪詢 Telegram、分派指令、
並透過 strategy 框架（PortfolioTracker / run_strategies）操作虛擬組合。
請依需求增刪指令、換上你自己的策略。

執行：python -m scripts.run_bot   （需在 .env 設好 TELEGRAM_TOKEN / TELEGRAM_CHAT_ID）
"""

import time

from config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN
from services.telegram import get_updates
from services.telegram import send_message as send_msg
from strategy import PortfolioTracker, run_strategies
from strategy.example_strategy import TechnicalRankingStrategy

# 註冊要跑的策略（範例：純技術排名；換成你自己的 Strategy 子類）
STRATEGIES = [TechnicalRankingStrategy()]

# 上次 /scan 的題材（供 /research <編號> 查；同一 bot 行程內有效）
_last_themes = []

HELP = (
    '可用指令：\n'
    '/help — 顯示說明\n'
    '/status — 各群組績效摘要\n'
    '/positions — 目前持倉\n'
    '/run — 執行一次策略週期\n'
    '/report — 完整文字報告\n'
    '/scan — 掃描熱門投資題材（編號列出，需開啟 THEME_RESEARCH）\n'
    '/research <編號或題材> — 對題材做深度研究並產 PDF（可直接打 /scan 的編號）'
)


def _status_summary(tracker: PortfolioTracker) -> str:
    lines = ['📊 策略群組摘要']
    for group in tracker.active_groups:
        perf = tracker.get_performance(group)
        lines.append(
            f"{group} {tracker.state['groups'][group].get('current_theme') or ''} "
            f"市值 ${perf.get('total_value', 0):,.0f}｜損益 {perf.get('total_pnl_pct', 0):+.1f}%"
            f"｜持倉 {perf.get('num_positions', 0)} 檔"
        )
    return '\n'.join(lines)


def _positions_summary(tracker: PortfolioTracker) -> str:
    lines = ['📋 目前持倉']
    any_pos = False
    for group in tracker.active_groups:
        for sym, pos in tracker.get_positions(group).items():
            any_pos = True
            lines.append(f"{group} {sym} x{pos.get('qty')} @ ${pos.get('avg_price', 0):.2f}")
    if not any_pos:
        lines.append('（無持倉）')
    return '\n'.join(lines)


def handle_message(text: str) -> str:
    """把一則指令文字轉成回覆字串。"""
    text = (text or '').strip()
    tracker = PortfolioTracker()

    if text in ('/start', '/help'):
        return HELP
    if text == '/status':
        return _status_summary(tracker)
    if text == '/positions':
        return _positions_summary(tracker)
    if text == '/run':
        run_strategies(STRATEGIES, tracker)
        return '✅ 策略週期已執行\n\n' + _status_summary(tracker)
    if text == '/report':
        return tracker.generate_report()
    if text == '/scan':
        from services.research import scan_themes

        themes = scan_themes()
        if not themes:
            return '（沒掃到題材，或未設定 AI 金鑰）'
        _last_themes[:] = themes  # 記住供 /research <編號> 用
        lines = ['🔥 熱門題材：']
        for i, (name, meta) in enumerate(themes, 1):
            lines.append(f"{i}. {name}（{meta.get('count', 0)} 則）— {meta.get('why', '')}")
        lines.append('\n用 /research <編號> 做深度研究（如 /research 1）')
        return '\n'.join(lines)
    if text.startswith('/research'):
        arg = text[len('/research') :].strip()
        if not arg:
            return '用法：/research <編號或題材>（先 /scan 取得編號）'
        # 純數字 → 取上次 /scan 的對應題材
        if arg.isdigit():
            idx = int(arg) - 1
            if not _last_themes:
                return '請先執行 /scan 取得題材編號'
            if not (0 <= idx < len(_last_themes)):
                return f'編號超出範圍（目前有 1-{len(_last_themes)}）'
            topic = _last_themes[idx][0]
        else:
            topic = arg
        from services.research import research_to_report

        send_msg(f'🔬 研究「{topic}」中，產 PDF 需數分鐘…')
        res = research_to_report(topic)
        if res.get('sent'):
            return f'✅ 完成，PDF 已傳送（{topic}）'
        if res.get('pdf_path'):
            return f'✅ 完成，PDF 已產出但未傳送：{res["pdf_path"]}'
        if res.get('md_path'):
            return f'⚠️ PDF 轉檔失敗，已產出 Markdown：{res["md_path"]}'
        return '❌ 報告產出失敗（請查看伺服器日誌）'
    return '未知指令。輸入 /help 看可用指令。'


def main():
    """輪詢 Telegram，分派指令。Ctrl-C 結束。"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print('⚠️ 請先在 .env 設定 TELEGRAM_TOKEN / TELEGRAM_CHAT_ID')
        return
    print('🤖 bot 啟動，輪詢中…（Ctrl-C 結束）')
    offset = None
    while True:
        try:
            updates = get_updates(offset=offset, timeout=30) or []
            for upd in updates:
                offset = upd['update_id'] + 1
                msg = upd.get('message') or {}
                text = msg.get('text', '')
                if not text:
                    continue
                try:
                    send_msg(handle_message(text))
                except Exception as e:
                    send_msg(f'❌ 指令處理失敗：{e}')
        except KeyboardInterrupt:
            print('\n👋 bot 結束')
            break
        except Exception as e:
            print(f'輪詢錯誤：{e}')
            time.sleep(5)


if __name__ == '__main__':
    main()
