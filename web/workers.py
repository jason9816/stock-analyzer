"""
背景更新 Worker — 兩層架構

快速迴圈（每 30 秒）：批次抓即時報價 → 合併歷史K線 → 重算指標 → 更新快取
慢速迴圈（每小時）：重下載歷史K線 → 跑完整分析（基本面/籌碼/新聞）→ 更新快取

兩個迴圈各自寫入獨立的 status 欄位（price_* / full_*），不再互相覆蓋，
前端可同時顯示「報價更新中」與「完整分析中（佇列 N 支）」。
"""

import threading
import time
from datetime import datetime

from core.quick_recalc import quick_recalc, recalc_status_and_advice
from data.fetchers import fetch_realtime_prices
from data.history import inject_live_candle, refresh_histories
from data.store import load_data, save_analysis_cache
from data.tw import get_tw_chinese_name
from web.helpers import analyze_parallel

_worker_status = {
    'us': {
        'running': False,
        'last_updated': '',
        'round': 0,
        'queue': [],
        'price_mode': 'idle',
        'price_current': '',  # 快速迴圈專用
        'full_mode': 'idle',
        'full_current': '',  # 慢速迴圈專用
        'price_updates': 0,
        'full_updates': 0,
    },
    'tw': {
        'running': False,
        'last_updated': '',
        'round': 0,
        'queue': [],
        'price_mode': 'idle',
        'price_current': '',
        'full_mode': 'idle',
        'full_current': '',
        'price_updates': 0,
        'full_updates': 0,
    },
}
_worker_lock = threading.Lock()


def _fast_price_loop(market, interval=30):
    """快速迴圈：每 interval 秒批次更新即時報價 + 重算指標"""
    status = _worker_status[market]

    while True:
        try:
            data = load_data(market)
            watchlist = data.get('watchlist', [])
            if not watchlist:
                time.sleep(30)
                continue

            cache = data.get('analysis_cache', {})

            with _worker_lock:
                status['price_mode'] = 'price'
                status['price_current'] = '批次抓報價...'

            prices = fetch_realtime_prices(watchlist, market)
            if not prices:
                with _worker_lock:
                    status['price_mode'] = 'idle'
                time.sleep(interval)
                continue

            updated_count = 0
            for sym in watchlist:
                if sym not in prices:
                    continue
                live = prices[sym]
                if not live.get('price'):
                    continue

                cache_entry = cache.get(sym, {})
                cached_result = cache_entry.get('data') if isinstance(cache_entry, dict) else None
                if not cached_result or 'error' in cached_result:
                    continue  # 沒有基底，等慢速迴圈跑完整分析

                try:
                    merged_hist = inject_live_candle(sym, live)
                    if merged_hist is None or len(merged_hist) < 20:
                        continue

                    updated = quick_recalc(cached_result, merged_hist)
                    updated = recalc_status_and_advice(updated)

                    updated['price'] = round(live['price'], 2)
                    prev = live.get('prev_close', 0)
                    if prev and prev > 0:
                        updated['chg'] = round(live['price'] - prev, 2)
                        updated['chg_pct'] = round((live['price'] - prev) / prev * 100, 2)

                    updated['price_source'] = live.get('source', 'unknown')
                    updated['price_time'] = live.get('time', '')

                    if market == 'tw':
                        cn = get_tw_chinese_name(sym)
                        if cn:
                            updated['name'] = cn

                    save_analysis_cache(sym, updated, market)
                    updated_count += 1
                except Exception as e:
                    print(f'⚠️ 快速更新 {sym} 失敗: {e}')

            with _worker_lock:
                status['price_updates'] += 1
                status['last_updated'] = datetime.now().strftime('%H:%M:%S')
                status['price_mode'] = 'idle'
                status['price_current'] = f'✅ {updated_count}/{len(watchlist)} 支已更新'

            time.sleep(interval)

        except Exception as e:
            print(f'⚠️ 快速迴圈 ({market}) 錯誤: {e}')
            time.sleep(10)


def _slow_full_loop(market, batch_size=2, interval_hours=1):
    """慢速迴圈：每 interval_hours 小時跑一次完整分析"""
    status = _worker_status[market]

    # 啟動時等較久，讓快速迴圈先建立即時數據（錯開避免同時重分析）
    initial_delay = 60 if market == 'tw' else 120
    time.sleep(initial_delay)

    while True:
        try:
            data = load_data(market)
            watchlist = data.get('watchlist', [])
            if not watchlist:
                time.sleep(60)
                continue

            cache = data.get('analysis_cache', {})

            now = datetime.now()
            needs_full = []
            for sym in watchlist:
                if sym not in cache or 'error' in cache.get(sym, {}):
                    needs_full.append((sym, 999999))
                elif cache[sym].get('update_type') == 'quick':
                    needs_full.append((sym, 888888))
                else:
                    try:
                        ut = datetime.strptime(
                            cache[sym].get('updated_at', ''), '%Y-%m-%d %H:%M:%S'
                        )
                        age = (now - ut).total_seconds()
                        if age > interval_hours * 3600:
                            needs_full.append((sym, age))
                    except (ValueError, TypeError):
                        needs_full.append((sym, 999999))

            if not needs_full:
                with _worker_lock:
                    status['full_mode'] = 'idle'
                    status['full_current'] = ''
                    status['queue'] = []
                time.sleep(300)  # 5 分鐘後再檢查
                continue

            needs_full.sort(key=lambda x: -x[1])

            with _worker_lock:
                status['full_mode'] = 'history'
                status['full_current'] = '更新歷史K線...'

            all_syms = [s[0] for s in needs_full]
            try:
                refresh_histories(all_syms, market)
            except Exception as e:
                print(f'⚠️ 歷史K線批次更新失敗: {e}')

            for i in range(0, len(needs_full), batch_size):
                batch = [s[0] for s in needs_full[i : i + batch_size]]
                with _worker_lock:
                    status['full_mode'] = 'full'
                    status['full_current'] = ', '.join(batch)
                    status['queue'] = [s[0] for s in needs_full[i + batch_size :]]

                results = analyze_parallel(batch, max_workers=batch_size)
                for r in results:
                    if r and 'error' not in r:
                        r['update_type'] = 'full'
                        save_analysis_cache(r['symbol'], r, market)
                        if market == 'tw':
                            cn = get_tw_chinese_name(r['symbol'])
                            if cn:
                                r['name'] = cn

                with _worker_lock:
                    status['last_updated'] = datetime.now().strftime('%H:%M:%S')

                time.sleep(10)

            with _worker_lock:
                status['round'] += 1
                status['full_updates'] += 1
                status['full_current'] = ''
                status['queue'] = []
                status['full_mode'] = 'idle'

            time.sleep(interval_hours * 3600)

        except Exception as e:
            print(f'⚠️ 慢速迴圈 ({market}) 錯誤: {e}')
            time.sleep(30)


def start_background_workers(markets=('us', 'tw')):
    """啟動指定市場的背景更新 worker（快速 + 慢速雙迴圈）"""
    for mkt in markets:
        _worker_status[mkt]['running'] = True
        threading.Thread(target=_fast_price_loop, args=(mkt,), daemon=True).start()
        print(f'⚡ 快速報價 worker 已啟動：{mkt}（每 30 秒）')
        threading.Thread(target=_slow_full_loop, args=(mkt,), daemon=True).start()
        print(f'🔄 完整分析 worker 已啟動：{mkt}（每 1 小時）')
