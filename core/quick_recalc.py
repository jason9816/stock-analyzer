"""
快速重算模組 — 用即時價格更新技術指標
不重新下載歷史數據，只用快取的歷史K線 + 即時價格重算
"""

from datetime import datetime

import numpy as np
import pandas as pd

from core.indicators import (
    calc_adx,
    calc_atr,
    calc_bollinger,
    calc_kd,
    calc_macd,
    calc_mfi,
    calc_obv,
    calc_rsi,
    calc_vwap,
)
from core.signals import calc_levels, calc_mid_trend, calc_swing_signal


def quick_recalc(cached_result: dict, hist: pd.DataFrame, info: dict = None) -> dict:
    """
    快速重算：用新的歷史+即時合併 DataFrame 更新技術指標

    Args:
        cached_result: 之前 get_stock_analysis() 的完整結果 dict
        hist: 已合併今天即時數據的完整 DataFrame (OHLCV)
        info: yfinance info dict (可選，用於 mid_trend 的 52wk high/low)

    Returns:
        更新後的 result dict（原地修改 + 返回）
    """
    if hist is None or len(hist) < 20:
        return cached_result

    result = cached_result.copy()

    # ── 重算所有技術指標 ──
    hist['MA5'] = hist['Close'].rolling(5).mean()
    hist['MA10'] = hist['Close'].rolling(10).mean()
    hist['MA20'] = hist['Close'].rolling(20).mean()
    hist['MA60'] = hist['Close'].rolling(60).mean()
    hist['RSI'] = calc_rsi(hist['Close'])
    macd_line, signal_line, macd_hist = calc_macd(hist['Close'])
    hist['MACD'] = macd_line
    hist['MACD_signal'] = signal_line
    hist['MACD_hist'] = macd_hist
    bb_up, bb_mid, bb_low = calc_bollinger(hist['Close'])
    hist['BB_upper'] = bb_up
    hist['BB_mid'] = bb_mid
    hist['BB_lower'] = bb_low
    kd_k, kd_d = calc_kd(hist['High'], hist['Low'], hist['Close'])
    hist['KD_K'] = kd_k
    hist['KD_D'] = kd_d
    hist['ATR'] = calc_atr(hist['High'], hist['Low'], hist['Close'])
    hist['OBV'] = calc_obv(hist['Close'], hist['Volume'])
    adx, di_plus, di_minus = calc_adx(hist['High'], hist['Low'], hist['Close'])
    hist['ADX'] = adx
    hist['DI_plus'] = di_plus
    hist['DI_minus'] = di_minus
    hist['MFI'] = calc_mfi(hist['High'], hist['Low'], hist['Close'], hist['Volume'])
    hist['VWAP'] = calc_vwap(hist['High'], hist['Low'], hist['Close'], hist['Volume'])

    # ── 更新價格相關欄位 ──
    cp = hist['Close'].iloc[-1]
    prev = hist['Close'].iloc[-2]
    chg = round(cp - prev, 2)
    chg_pct = round(chg / prev * 100, 2) if prev else 0

    result['price'] = round(cp, 2)
    result['chg'] = chg
    result['chg_pct'] = chg_pct

    # ── 技術指標數值 ──
    rsi_val = round(hist['RSI'].iloc[-1], 1) if not np.isnan(hist['RSI'].iloc[-1]) else 'N/A'
    macd_val = round(hist['MACD'].iloc[-1], 2)
    macd_sig = round(hist['MACD_signal'].iloc[-1], 2)
    macd_hist_val = round(hist['MACD_hist'].iloc[-1], 2)
    macd_cross = "金叉（多）" if macd_val > macd_sig else "死叉（空）"

    result['rsi'] = rsi_val
    result['macd_val'] = macd_val
    result['macd_sig'] = macd_sig
    result['macd_hist_val'] = macd_hist_val
    result['macd_cross'] = macd_cross

    # 量能
    vol_5 = hist['Volume'].tail(5).mean()
    vol_20 = hist['Volume'].tail(20).mean()
    vol_ratio = round(vol_5 / vol_20, 2) if vol_20 > 0 else 1
    vol_trend = "放量" if vol_ratio > 1.3 else "縮量" if vol_ratio < 0.7 else "量能正常"
    result['vol_ratio'] = vol_ratio
    result['vol_trend'] = vol_trend

    # ── 壓力支撐 ──
    levels = calc_levels(hist, cp)
    pressures = sorted([l for l in levels if l['kind'] == 'P'], key=lambda x: x['price'])
    supports = sorted([l for l in levels if l['kind'] == 'S'], key=lambda x: -x['price'])
    nearest_p = pressures[0]['price'] if pressures else round(cp * 1.05, 2)
    nearest_s = supports[0]['price'] if supports else round(cp * 0.95, 2)
    if nearest_p <= cp:
        nearest_p = round(cp * 1.05, 2)
    if nearest_s >= cp:
        nearest_s = round(cp * 0.95, 2)

    result['pressures'] = pressures[:5]
    result['supports'] = supports[:5]
    result['nearest_p'] = nearest_p
    result['nearest_s'] = nearest_s

    # ── 52 週位置 ──
    w52h = result.get('w52h', 0)
    w52l = result.get('w52l', 0)
    if w52h > w52l:
        result['w52_pos'] = round((cp - w52l) / (w52h - w52l) * 100, 1)

    # ── 中期趨勢 ──
    try:
        from core.indicators import get_index_history

        index_sym = '^TWII' if any(s in result.get('symbol', '') for s in ['.TW']) else '^GSPC'
        index_hist = get_index_history(index_sym)
        mid = calc_mid_trend(
            hist, index_hist=index_hist, w52h=w52h if w52h else None, w52l=w52l if w52l else None
        )
        result['mid_trend'] = mid
    except Exception:
        mid = result.get('mid_trend', {'score': 0, 'stage': '未知'})

    # ── 短線信號 ──
    try:
        earnings_days = result.get('earnings_days')
        sector_perf = result.get('sector_perf', {})
        swing = calc_swing_signal(
            hist, info=info, sector_perf=sector_perf, earnings_days=earnings_days
        )
        result['swing'] = swing
    except Exception:
        pass

    # ── K 線圖表數據 ──
    result['dates'] = hist.index.tolist()
    result['opens'] = [round(v, 2) for v in hist['Open'].tolist()]
    result['highs'] = [round(v, 2) for v in hist['High'].tolist()]
    result['lows'] = [round(v, 2) for v in hist['Low'].tolist()]
    result['closes'] = [round(v, 2) for v in hist['Close'].tolist()]
    result['volumes'] = [int(v) for v in hist['Volume'].tolist()]
    result['ma5'] = [None if np.isnan(v) else round(v, 2) for v in hist['MA5'].tolist()]
    result['ma10'] = [None if np.isnan(v) else round(v, 2) for v in hist['MA10'].tolist()]
    result['ma20'] = [None if np.isnan(v) else round(v, 2) for v in hist['MA20'].tolist()]
    result['ma60'] = [None if np.isnan(v) else round(v, 2) for v in hist['MA60'].tolist()]
    result['bb_upper'] = [None if np.isnan(v) else round(v, 2) for v in hist['BB_upper'].tolist()]
    result['bb_lower'] = [None if np.isnan(v) else round(v, 2) for v in hist['BB_lower'].tolist()]
    result['rsi_data'] = [None if np.isnan(v) else round(v, 1) for v in hist['RSI'].tolist()]
    result['macd_data'] = [None if np.isnan(v) else round(v, 2) for v in hist['MACD'].tolist()]
    result['macd_signal_data'] = [
        None if np.isnan(v) else round(v, 2) for v in hist['MACD_signal'].tolist()
    ]
    result['macd_hist_data'] = [
        None if np.isnan(v) else round(v, 2) for v in hist['MACD_hist'].tolist()
    ]

    # ── 更新時間戳 ──
    result['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    result['update_type'] = 'quick'  # 標記這是快速更新

    return result


def recalc_status_and_advice(result: dict) -> dict:
    """
    根據更新後的指標重算趨勢狀態和操作建議
    （簡化版，不重算完整的建議文字，只更新 status/action）
    """
    mid = result.get('mid_trend', {})
    mid_score = mid.get('score', 0)
    swing = result.get('swing', {})
    sw_score = swing.get('score', 0)

    # 趨勢判斷
    if mid_score >= 60:
        result['status'] = f"🔥 中線強勢（{mid.get('stage', '')}）"
        result['status_color'] = "#22c55e"
        result['status_bg'] = "#14532d"
    elif mid_score >= 30:
        result['status'] = f"📈 中線偏多（{mid.get('stage', '')}）"
        result['status_color'] = "#4ade80"
        result['status_bg'] = "#14532d"
    elif mid_score >= 10:
        result['status'] = f"⚡ 中線觀望（{mid.get('stage', '')}）"
        result['status_color'] = "#fbbf24"
        result['status_bg'] = "#713f12"
    elif mid_score >= -10:
        result['status'] = f"⚡ 盤整觀望（{mid.get('stage', '')}）"
        result['status_color'] = "#fbbf24"
        result['status_bg'] = "#713f12"
    elif mid_score >= -30:
        result['status'] = f"🔻 中線偏空（{mid.get('stage', '')}）"
        result['status_color'] = "#f87171"
        result['status_bg'] = "#7f1d1d"
    else:
        result['status'] = f"🔻 中線空頭（{mid.get('stage', '')}）"
        result['status_color'] = "#f87171"
        result['status_bg'] = "#7f1d1d"

    # 短線操作建議（簡化）
    trend_bullish = mid_score >= 30
    trend_bearish = mid_score < -10

    if sw_score >= 30 and not trend_bearish:
        result['short_action'] = "買入"
        result['short_action_color'] = "#4ade80"
    elif sw_score <= -30:
        if trend_bullish:
            result['short_action'] = "短線過熱，等回檔"
            result['short_action_color'] = "#fbbf24"
        else:
            result['short_action'] = "賣出/觀望"
            result['short_action_color'] = "#f87171"
    elif 15 <= sw_score < 30 and not trend_bearish:
        result['short_action'] = "逢低留意"
        result['short_action_color'] = "#fbbf24"
    elif -29 <= sw_score <= -15:
        if trend_bullish:
            result['short_action'] = "持有，留意回檔"
            result['short_action_color'] = "#fbbf24"
        else:
            result['short_action'] = "減碼/觀望"
            result['short_action_color'] = "#fbbf24"
    else:
        result['short_action'] = "觀望"
        result['short_action_color'] = "#94a3b8"

    # 中線操作建議（簡化）
    if trend_bullish:
        if sw_score >= 15:
            result['mid_action'] = "買入"
            result['mid_action_color'] = "#4ade80"
        elif sw_score <= -15:
            result['mid_action'] = "持有/減碼"
            result['mid_action_color'] = "#fbbf24"
        else:
            result['mid_action'] = "輕倉試單"
            result['mid_action_color'] = "#fbbf24"
    elif trend_bearish:
        result['mid_action'] = "不建議"
        result['mid_action_color'] = "#f87171"
    else:
        if sw_score >= 30:
            result['mid_action'] = "逢低佈局"
            result['mid_action_color'] = "#4ade80"
        else:
            result['mid_action'] = "觀望"
            result['mid_action_color'] = "#94a3b8"

    return result
