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

HELP = (
    '可用指令：\n'
    '/help — 顯示說明\n'
    '/status — 各群組績效摘要\n'
    '/positions — 目前持倉\n'
    '/run — 執行一次策略週期\n'
    '/report — 完整文字報告'
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
