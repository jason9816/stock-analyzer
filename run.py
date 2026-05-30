"""
股票分析系統 — 主入口

啟動 Flask 伺服器（依 FEATURE_FLAGS 註冊功能）+ 背景 worker + 排程 + 對外導出。
所有功能開關與密鑰見 .env（範本 .env.example）。
"""

import threading
import time

import schedule

from config import FEATURE_FLAGS, WEB_PORT
from services.tunnel import open_tunnel
from web import create_app
from web.workers import start_background_workers

app = create_app()


def _start_scheduler():
    """排程：大盤快取更新、每日題材研究報告（依 flag 啟用）。"""
    from core.indicators import refresh_all_index_cache

    schedule.every().day.at("09:00").do(
        lambda: threading.Thread(target=refresh_all_index_cache, daemon=True).start()
    )

    if FEATURE_FLAGS['THEME_RESEARCH']:
        from services.research import daily_report

        schedule.every().day.at("08:00").do(
            lambda: threading.Thread(target=daily_report, daemon=True).start()
        )

    def _loop():
        print("⏰ 排程已啟動")
        while True:
            schedule.run_pending()
            time.sleep(30)

    threading.Thread(target=_loop, daemon=True).start()


if __name__ == '__main__':
    _start_scheduler()

    # 背景股票更新 worker（依啟用的市場）
    if FEATURE_FLAGS['BG_WORKERS']:
        markets = []
        if FEATURE_FLAGS['US_MARKET']:
            markets.append('us')
        if FEATURE_FLAGS['TW_MARKET']:
            markets.append('tw')
        if markets:
            start_background_workers(markets=tuple(markets))

    # 對外導出（none / ngrok / cloudflare，由 .env 的 TUNNEL_PROVIDER 決定）
    open_tunnel(WEB_PORT)

    print(f" * Starting local server at: http://127.0.0.1:{WEB_PORT}")
    app.run(port=WEB_PORT)
