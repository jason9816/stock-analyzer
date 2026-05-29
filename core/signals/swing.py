"""
短線波段信號（swing, 1-5 日）— 純技術面計分

設計原則（見 docs 策略報告）：
  1. headline `score` 只反映「價/量/波動/短期動量/均值回歸」——不混入中長期
     基本面與籌碼（那些由 mid_trend / chip 各自獨立計分）。
  2. 趨勢強度（ADX）與市場體制（VIX regime）作為乘數縮放技術分。
  3. 訊號離散度（confidence）量化不確定性，並據以給出建議部位大小。
  4. 每個權重附文獻；門檻為經驗值，待自家回測校準。

backward-compat：`details` 仍提供 fundamental_score / theme_score 供
掃描器與前端顯示，但這兩者「不計入」headline score（避免週期污染）。
"""

import numpy as np
import pandas as pd

from core.indicators import calc_fibonacci_levels, calc_rsi

from .pattern import calc_candle_pattern


# ══════════════════════════════════════════════════════════════
# 市場體制（VIX regime）— 作為技術分乘數
# 啟發：Hamilton (1989) regime-switching, Econometrica
#   https://doi.org/10.2307/1912559
# VIX 作為恐慌指標：Whaley (2000) "The Investor Fear Gauge", JPM
#   https://doi.org/10.3905/jpm.2000.319728
# 註：固定門檻為簡化版；嚴謹做法用 HMM/GMM regime detection。
# ══════════════════════════════════════════════════════════════
def get_market_regime(vix_value):
    """
    依 VIX 判定市場體制，回傳技術信號乘數與謹慎面乘數。
    - panic    VIX > 35 → 技術分打 5 折、風險加倍
    - high_vol VIX 25-35 → 技術分打 7 折
    - normal   VIX 15-25 → 標準
    - complacent VIX < 15 → 過度樂觀，謹慎面略加
    """
    if vix_value is None or vix_value == 'N/A':
        return {'regime': 'unknown', 'tech_mult': 1.0, 'caution_mult': 1.0, 'label': '未知'}
    try:
        vix = float(vix_value)
    except (ValueError, TypeError):
        return {'regime': 'unknown', 'tech_mult': 1.0, 'caution_mult': 1.0, 'label': '未知'}

    if vix > 35:
        return {
            'regime': 'panic',
            'tech_mult': 0.5,
            'caution_mult': 1.5,
            'label': f'🔴 恐慌 (VIX {vix:.0f})',
        }
    elif vix > 25:
        return {
            'regime': 'high_vol',
            'tech_mult': 0.7,
            'caution_mult': 1.2,
            'label': f'🟠 高波動 (VIX {vix:.0f})',
        }
    elif vix > 15:
        return {
            'regime': 'normal',
            'tech_mult': 1.0,
            'caution_mult': 1.0,
            'label': f'🟢 正常 (VIX {vix:.0f})',
        }
    else:
        return {
            'regime': 'complacent',
            'tech_mult': 1.0,
            'caution_mult': 0.8,
            'label': f'🔵 低波動 (VIX {vix:.0f})',
        }


# ══════════════════════════════════════════════════════════════
# 指標衝突檢測（手寫啟發式）— 方向矛盾時降低可信度
# 概念啟發（Decision-Focused Learning，本函式並未實作其數學）：
#   Wilder et al. (2019) https://arxiv.org/abs/1809.05504
#   Elmachtoub & Grigas (2022) https://arxiv.org/abs/1710.08005
# ══════════════════════════════════════════════════════════════
def detect_signal_conflicts(details):
    """檢測技術指標之間的方向矛盾，回傳 {conflicts, penalty}。"""
    conflicts = []
    penalty = 0

    rsi = details.get('rsi', 50)
    macd_hist = details.get('macd_hist', 0)
    adx = details.get('adx', 25)
    bb_pos = details.get('bb_position', 50)

    if rsi > 65 and macd_hist < 0:
        conflicts.append("RSI 偏高但 MACD 柱為負 — 動能不一致")
        penalty -= 5
    elif rsi < 35 and macd_hist > 0:
        conflicts.append("RSI 偏低但 MACD 柱為正 — 可能假訊號")
        penalty -= 5

    if bb_pos > 90 and rsi < 40:
        conflicts.append("價格在布林上軌但 RSI 不高 — 異常分歧")
        penalty -= 5
    elif bb_pos < 10 and rsi > 60:
        conflicts.append("價格在布林下軌但 RSI 不低 — 異常分歧")
        penalty -= 5

    if adx < 15 and (rsi > 70 or rsi < 30):
        conflicts.append("ADX 極低但 RSI 極端 — 無趨勢下的極端值不可信")
        penalty -= 5

    return {'conflicts': conflicts, 'penalty': penalty}


# ══════════════════════════════════════════════════════════════
# 信號穩定度（heuristic 一致性）— 過去 5 日 RSI/MACD 方向一致性
# 註：這「不是」conformal prediction，未量化真正的不確定性。
# 若要做正統時間序列不確定性量化（預測區間 + 覆蓋保證）參考：
#   Gibbs & Candès, Adaptive Conformal Inference, NeurIPS 2021
#   https://arxiv.org/abs/2106.00170
# 本實作用一致性百分比作為「信心」，並據以縮放建議部位（見 _position_size）。
# ══════════════════════════════════════════════════════════════
def calc_signal_confidence(hist, score):
    """回傳 {confidence, stability, label}；stability 為 0-100 一致性。"""
    if len(hist) < 35:
        return {'confidence': 'low', 'stability': 0, 'label': '⚪ 數據不足'}

    rsi_vals = hist['RSI'].tail(5).values if 'RSI' in hist.columns else []
    macd_vals = hist['MACD_hist'].tail(5).values if 'MACD_hist' in hist.columns else []

    rsi_dirs = []
    for v in rsi_vals:
        if np.isnan(v):
            continue
        rsi_dirs.append(1 if v > 60 else (-1 if v < 40 else 0))

    macd_dirs = [1 if v > 0 else -1 for v in macd_vals if not np.isnan(v)]

    consistency = 0.0
    total = 0.0
    if len(rsi_dirs) >= 3:
        consistency += sum(1 for d in rsi_dirs if d == rsi_dirs[-1]) / len(rsi_dirs)
        total += 1
    if len(macd_dirs) >= 3:
        consistency += sum(1 for d in macd_dirs if d == macd_dirs[-1]) / len(macd_dirs)
        total += 1

    score_sign = 1 if score > 0 else (-1 if score < 0 else 0)
    if rsi_dirs and rsi_dirs[-1] == score_sign:
        consistency += 0.5
        total += 0.5
    if macd_dirs and macd_dirs[-1] == score_sign:
        consistency += 0.5
        total += 0.5

    stability = round(consistency / total * 100, 1) if total > 0 else 50

    if stability >= 75:
        return {
            'confidence': 'high',
            'stability': stability,
            'label': '🟢 信號穩定（多指標方向一致）',
        }
    elif stability >= 50:
        return {
            'confidence': 'medium',
            'stability': stability,
            'label': '🟡 信號普通（部分指標分歧）',
        }
    return {'confidence': 'low', 'stability': stability, 'label': '🔴 信號不穩（指標方向矛盾）'}


# ══════════════════════════════════════════════════════════════
# 建議部位大小 — fractional Kelly × 波動率目標 × 信心
# Kelly (1956) "A New Interpretation of Information Rate", BSTJ
#   https://www.princeton.edu/~wbialek/rome/refs/kelly_56.pdf
# fractional Kelly（full Kelly 波動過大，實務用 1/4~1/2）：
#   MacLean, Thorp & Ziemba (2011)
#   https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf
# 波動率目標（高波動降曝險）：Moreira & Muir (2017), JF
#   https://doi.org/10.1111/jofi.12513
# ══════════════════════════════════════════════════════════════
def _position_size(score, stability, atr_pct, regime_caution):
    """
    將 -100~+100 分數轉成 0~1 建議部位比例（僅多頭側給部位，空頭回 0）。
      1) 分數→勝率 p（sigmoid），edge = 2p-1
      2) fractional Kelly：f = 0.5 * max(edge, 0)
      3) 波動率目標：目標日波動 2%，÷ 實際 ATR%
      4) × 信心(stability)，再 × 體制謹慎係數倒數
    回傳 0~1（上限 1.0）。
    """
    if score <= 0:
        return 0.0
    p = 1.0 / (1.0 + np.exp(-score / 25.0))  # score=25→~0.73, 50→~0.88
    edge = max(2 * p - 1, 0.0)
    kelly = 0.5 * edge  # fractional (half) Kelly
    vol_target = 0.02
    vol_scale = min(vol_target / atr_pct, 1.5) if atr_pct and atr_pct > 0 else 1.0
    conf_scale = max(min(stability / 100.0, 1.0), 0.2)
    size = kelly * vol_scale * conf_scale / max(regime_caution, 1e-6)
    return round(float(min(max(size, 0.0), 1.0)), 3)


def calc_swing_signal(hist, info=None, sector_perf=None, earnings_days=None, vix=None):
    """
    短線波段信號（純技術面）。

    架構（皆為價/量/波動/動量，不含中長期基本面與籌碼）：
      Layer 0 base       : MACD / 布林 / 均線 / 連漲跌 / 量價背離
      Layer 1 momentum   : RSI 或 KD 擇一（取較極端者）
      Layer 2 confirm    : OBV 背離 + K 線形態（K 線低權重）
      Layer 3 level      : VWAP / Fibonacci
      Layer 4 mfi        : 資金流極端過濾
      gate: tech_score = (base+momentum+confirm+level+mfi) × ADX 乘數 × VIX 體制乘數
      + ConnorsRSI(均值回歸) + RVOL(量能確認) + 衝突懲罰

    回傳 score(-100~+100), signal, signal_color, action, reasons, details。
    details 另含 fundamental_score / theme_score（顯示用，不計入 score）、
    confidence、position（建議部位 0~1）。

    量價基礎：Karpoff (1987) JFQA — https://doi.org/10.2307/2330874
    """
    cp = hist['Close'].iloc[-1]
    rsi = hist['RSI'].iloc[-1] if 'RSI' in hist.columns else 50
    reasons = []
    details = {}

    # ═══ Layer 0: base（MACD + BB + 均線 + 連漲跌 + 量價背離）═══
    base_score = 0
    mh = hist['MACD_hist'].iloc[-1]
    mh_prev = hist['MACD_hist'].iloc[-2]
    mh_3ago = hist['MACD_hist'].iloc[-4] if len(hist) > 4 else mh_prev

    if mh > 0:
        if mh < mh_prev < mh_3ago:
            base_score -= 15
            reasons.append("MACD 柱狀體連續縮小，多頭動能衰退")
        elif mh > mh_prev > mh_3ago:
            base_score += 10
            reasons.append("MACD 柱狀體持續放大，多頭動能增強")
        elif mh < mh_prev:
            base_score -= 8
    else:
        if mh > mh_prev > mh_3ago:
            base_score += 15
            reasons.append("MACD 負柱縮小，空頭力道衰退")
        elif mh < mh_prev < mh_3ago:
            base_score -= 10
            reasons.append("MACD 負柱擴大，空頭動能增強")
        elif mh > mh_prev:
            base_score += 8

    macd_line = hist['MACD'].iloc[-1]
    signal_line = hist['MACD_signal'].iloc[-1]
    macd_prev = hist['MACD'].iloc[-2]
    signal_prev = hist['MACD_signal'].iloc[-2]
    if macd_line > signal_line and macd_prev <= signal_prev:
        base_score += 12
        reasons.append("⚡ MACD 金叉")
    elif macd_line < signal_line and macd_prev >= signal_prev:
        base_score -= 12
        reasons.append("⚡ MACD 死叉")
    details['macd_hist'] = round(mh, 3)

    # 量價背離（Karpoff 1987：價量同向；背離為警訊）
    if len(hist) >= 5:
        closes_5 = hist['Close'].tail(5).values
        vols_5 = hist['Volume'].tail(5).values
        price_rising = closes_5[-1] > closes_5[0]
        vol_declining = vols_5[-1] < vols_5[0] and np.mean(vols_5[-3:]) < np.mean(vols_5[:3])
        if price_rising and vol_declining:
            base_score -= 18
            reasons.append("⚠️ 量價背離：股價漲但量縮")
            details['vol_price_diverge'] = True
        elif closes_5[-1] < closes_5[0] and vols_5[-1] < vols_5[0]:
            base_score += 12
            reasons.append("下跌量縮，賣壓減輕")
            details['vol_price_diverge'] = False
        else:
            details['vol_price_diverge'] = False
    else:
        details['vol_price_diverge'] = False

    # 布林帶
    bb_upper = hist['BB_upper'].iloc[-1]
    bb_lower = hist['BB_lower'].iloc[-1]
    bb_mid = hist['BB_mid'].iloc[-1]
    bb_pos = round((cp - bb_lower) / (bb_upper - bb_lower) * 100, 1) if bb_upper > bb_lower else 50
    details['bb_position'] = bb_pos

    # 布林上軌：放量站上=突破（加分）；縮量觸及=過熱（扣分）
    if cp >= bb_upper:
        vol_today = hist['Volume'].iloc[-1]
        vol_ma20 = hist['Volume'].tail(20).mean()
        vol_ratio = vol_today / vol_ma20 if vol_ma20 > 0 else 1
        ma20_val = hist['MA20'].iloc[-1] if 'MA20' in hist.columns else bb_mid
        if vol_ratio > 1.5 and cp > ma20_val and rsi < 80:
            base_score += 8
            reasons.append(f"放量突破布林上軌（量比 {vol_ratio:.1f}x），強勢突破")
        else:
            base_score -= 12
            reasons.append("股價觸及布林上軌，短線過熱")
    elif cp <= bb_lower:
        base_score += 12
        reasons.append("股價觸及布林下軌，短線超跌")

    bb_width = (bb_upper - bb_lower) / bb_mid * 100 if bb_mid > 0 else 0
    details['bb_squeeze'] = bb_width < 8
    if bb_width < 8:
        reasons.append(f"布林帶收窄（{bb_width:.1f}%），即將變盤")

    # 均線位置
    ma5 = hist['MA5'].iloc[-1]
    ma20 = hist['MA20'].iloc[-1]
    if cp > ma5 > ma20:
        base_score += 8
    elif cp < ma5 < ma20:
        base_score -= 8

    # 連漲/連跌（持平中斷連續）
    streak = 0
    for i in range(-1, -min(10, len(hist)), -1):
        if hist['Close'].iloc[i] > hist['Close'].iloc[i - 1]:
            if streak >= 0:
                streak += 1
            else:
                break
        elif hist['Close'].iloc[i] < hist['Close'].iloc[i - 1]:
            if streak <= 0:
                streak -= 1
            else:
                break
        else:
            break
    details['streak'] = streak
    if streak >= 5:
        base_score -= 12
        reasons.append(f"已連漲 {streak} 天，獲利回吐壓力大")
    elif streak <= -5:
        base_score += 12
        reasons.append(f"已連跌 {abs(streak)} 天，恐慌可能過度")
    elif streak >= 3:
        base_score -= 5
    elif streak <= -3:
        base_score += 5

    # ═══ Layer 1: momentum（RSI 或 KD 擇一）═══
    rsi = hist['RSI'].iloc[-1]
    rsi_prev = hist['RSI'].iloc[-2]
    rsi_dir = rsi - rsi_prev
    details['rsi'] = round(rsi, 1)
    details['rsi_dir'] = round(rsi_dir, 1)
    details['rsi_trend'] = '↑' if rsi_dir > 1 else ('↓' if rsi_dir < -1 else '→')

    rsi_score = 0
    if rsi > 75:
        rsi_score = -25 + (-15 if rsi_dir < 0 else 0)
    elif rsi > 65:
        rsi_score = -10 + (-10 if rsi_dir < -2 else 0)
    elif rsi < 25:
        rsi_score = 25 + (15 if rsi_dir > 0 else 0)
    elif rsi < 35:
        rsi_score = 10 + (10 if rsi_dir > 2 else 0)
    else:
        if rsi_dir < -5:
            rsi_score = -8
        elif rsi_dir > 5:
            rsi_score = 8

    kd_score = 0
    k_val = d_val = None
    if 'KD_K' in hist.columns and 'KD_D' in hist.columns:
        k_val = hist['KD_K'].iloc[-1]
        d_val = hist['KD_D'].iloc[-1]
        k_prev = hist['KD_K'].iloc[-2]
        d_prev = hist['KD_D'].iloc[-2]
        details['kd_k'] = round(k_val, 1)
        details['kd_d'] = round(d_val, 1)
        if k_val > 80 and d_val > 80:
            kd_score = -12
            if k_val < d_val and k_prev >= d_prev:
                kd_score -= 15
        elif k_val < 20 and d_val < 20:
            kd_score = 12
            if k_val > d_val and k_prev <= d_prev:
                kd_score += 15
        elif k_val > d_val and k_prev <= d_prev:
            kd_score = 8
        elif k_val < d_val and k_prev >= d_prev:
            kd_score = -8

    if abs(rsi_score) >= abs(kd_score):
        momentum_score = rsi_score
        if rsi_score > 0:
            reasons.append(f"RSI {rsi:.0f} 偏低，動能回升中")
        elif rsi_score < 0:
            reasons.append(f"RSI {rsi:.0f} 偏高，動能過熱")
        details['momentum_source'] = 'RSI'
    else:
        momentum_score = kd_score
        if kd_score > 0:
            reasons.append(f"KD 低檔金叉（K:{k_val:.0f} D:{d_val:.0f}）")
        elif kd_score < 0:
            reasons.append(f"KD 高檔死叉（K:{k_val:.0f} D:{d_val:.0f}）")
        details['momentum_source'] = 'KD'

    # ═══ Layer 2: confirm（OBV 背離 + K 線形態，K 線低權重）═══
    # K 線實證上多無顯著獲利（Marshall et al. 2006, JBF
    #   https://doi.org/10.1016/j.jbankfin.2005.08.001），故僅作低權重確認，
    #   且需與動量同向、上限 ±10。
    confirm_score = 0
    momentum_dir = 1 if momentum_score > 0 else (-1 if momentum_score < 0 else 0)

    if 'OBV' in hist.columns and len(hist) >= 5:
        obv = hist['OBV']
        obv_5 = obv.iloc[-1] - obv.iloc[-5]
        price_5 = hist['Close'].iloc[-1] - hist['Close'].iloc[-5]
        if momentum_dir > 0 and price_5 < 0 and obv_5 > 0:
            confirm_score += 8
            reasons.append("✅ OBV 底背離確認：量能承接中")
        elif momentum_dir < 0 and price_5 > 0 and obv_5 < 0:
            confirm_score -= 8
            reasons.append("⚠️ OBV 頂背離確認：量能未跟上")
        if len(hist) >= 20 and momentum_dir > 0:
            obv_20h = obv.tail(20).max()
            p_20h = hist['Close'].tail(20).max()
            if obv.iloc[-1] >= obv_20h * 0.98 and cp >= p_20h * 0.98:
                confirm_score += 5
                reasons.append("OBV 與價格同步創高")

    candle = calc_candle_pattern(hist)
    details['candle'] = candle
    c_score = candle['score']
    # K 線低權重：與動量同向才採計，上限 ±10
    if momentum_dir > 0 and c_score > 0:
        confirm_score += min(c_score, 10)
    elif momentum_dir < 0 and c_score < 0:
        confirm_score += max(c_score, -10)
    elif momentum_dir == 0:
        confirm_score += int(c_score * 0.3)
    for p in candle['patterns']:
        reasons.append(p)
    if candle.get('vol_candle'):
        reasons.append(candle['vol_candle'])

    # ═══ Layer 3: level（VWAP + Fibonacci）═══
    level_score = 0
    if 'VWAP' in hist.columns and not np.isnan(hist['VWAP'].iloc[-1]):
        vwap_val = hist['VWAP'].iloc[-1]
        details['vwap'] = round(vwap_val, 2)
        details['vwap_dist'] = round((cp / vwap_val - 1) * 100, 1)
        if cp > vwap_val and momentum_dir >= 0:
            level_score += 3
        elif cp < vwap_val and momentum_dir <= 0:
            level_score -= 3

    if len(hist) >= 60:
        fib = calc_fibonacci_levels(hist)
        details['fibonacci'] = {k: round(v, 2) for k, v in fib.items()}
        for level_name, level_price in fib.items():
            if level_price == 0:
                continue
            dist = abs(cp / level_price - 1) * 100
            if dist < 2.0 and level_name in ['fib_382', 'fib_500', 'fib_618']:
                if cp < fib['fib_500'] and momentum_dir > 0:
                    level_score += 5
                    reasons.append(f"接近費氏支撐位 ({level_price:.1f})")
                elif cp > fib['fib_500'] and momentum_dir < 0:
                    level_score -= 3
                    reasons.append(f"接近費氏壓力位 ({level_price:.1f})")
                break

    # ═══ Layer 4: MFI 極端過濾 ═══
    mfi_score = 0
    if 'MFI' in hist.columns and not np.isnan(hist['MFI'].iloc[-1]):
        mfi_val = hist['MFI'].iloc[-1]
        details['mfi'] = round(mfi_val, 1)
        if mfi_val > 80:
            mfi_score -= 8
            reasons.append(f"MFI {mfi_val:.0f} 資金過熱")
        elif mfi_val < 20:
            mfi_score += 8
            reasons.append(f"MFI {mfi_val:.0f} 資金超賣")

    # ═══ gate: ADX 趨勢強度 × VIX 體制 ═══
    tech_raw = base_score + momentum_score + confirm_score + level_score + mfi_score

    adx_multiplier = 1.0
    if 'ADX' in hist.columns and not np.isnan(hist['ADX'].iloc[-1]):
        adx_val = hist['ADX'].iloc[-1]
        di_p = hist['DI_plus'].iloc[-1]
        di_m = hist['DI_minus'].iloc[-1]
        details['adx'] = round(adx_val, 1)
        details['di_plus'] = round(di_p, 1)
        details['di_minus'] = round(di_m, 1)
        if adx_val < 15:
            adx_multiplier = 0.4
            reasons.append(f"ADX {adx_val:.0f} 完全盤整，信號可信度低")
        elif adx_val < 20:
            adx_multiplier = 0.6
            reasons.append(f"ADX {adx_val:.0f} 趨勢微弱")
        elif adx_val > 40:
            if (di_p > di_m and tech_raw > 0) or (di_m > di_p and tech_raw < 0):
                adx_multiplier = 1.2
                reasons.append(f"ADX {adx_val:.0f} 強趨勢，信號加強")

    # VIX 體制乘數（真正套用，非死碼）
    regime = get_market_regime(vix)
    details['regime'] = regime
    if regime['regime'] not in ('unknown',):
        if regime['tech_mult'] != 1.0:
            reasons.append(f"{regime['label']} → 技術信號 ×{regime['tech_mult']}")

    tech_score = int(tech_raw * adx_multiplier * regime['tech_mult'])
    details['tech_score'] = tech_score

    # ═══ ConnorsRSI（短線均值回歸）═══
    # 公式：Connors, Alvarez & Radtke (2012)《An Introduction to ConnorsRSI》
    # ⚠️「65-75% 勝率」為業者宣稱，非同儕審查，待自家回測驗證。
    connors_rsi_score = 0
    try:
        close = hist['Close']
        if len(close) >= 110:
            rsi3 = calc_rsi(close, 3).iloc[-1]
            streak_series = pd.Series(0.0, index=close.index)
            for i in range(1, len(close)):
                if close.iloc[i] > close.iloc[i - 1]:
                    streak_series.iloc[i] = max(1, streak_series.iloc[i - 1] + 1)
                elif close.iloc[i] < close.iloc[i - 1]:
                    streak_series.iloc[i] = min(-1, streak_series.iloc[i - 1] - 1)
                else:
                    streak_series.iloc[i] = 0
            rsi_streak = calc_rsi(streak_series, 2).iloc[-1]
            roc1 = close.pct_change(1)
            lookback = min(100, len(roc1) - 1)
            pct_rank = (
                ((roc1.iloc[-lookback:] < roc1.iloc[-1]).sum() / lookback * 100)
                if lookback > 10
                else 50
            )
            connors_rsi = (
                50
                if (np.isnan(rsi3) or np.isnan(rsi_streak))
                else (rsi3 + rsi_streak + pct_rank) / 3
            )
            details['connors_rsi'] = round(connors_rsi, 1)
            sma200 = (
                close.rolling(200).mean().iloc[-1]
                if len(close) >= 200
                else close.rolling(min(len(close), 50)).mean().iloc[-1]
            )
            if connors_rsi < 10 and close.iloc[-1] > sma200:
                connors_rsi_score = 12
                reasons.append(f'ConnorsRSI {connors_rsi:.0f} 極度超賣（均值回歸買點）')
            elif connors_rsi < 20 and close.iloc[-1] > sma200:
                connors_rsi_score = 6
                reasons.append(f'ConnorsRSI {connors_rsi:.0f} 偏低（回彈機會）')
            elif connors_rsi > 90:
                connors_rsi_score = -10
                reasons.append(f'ConnorsRSI {connors_rsi:.0f} 極度過熱')
            elif connors_rsi > 80:
                connors_rsi_score = -5
                reasons.append(f'ConnorsRSI {connors_rsi:.0f} 偏高')
    except Exception:
        pass

    # ═══ RVOL 量能確認（Karpoff 1987：放量突破較可信）═══
    # 1.5/2.0 門檻為經驗值，待自家回測校準。
    rvol_score = 0
    if len(hist) >= 20:
        today_vol = hist['Volume'].iloc[-1]
        avg_vol_20 = hist['Volume'].tail(20).mean()
        rvol = today_vol / avg_vol_20 if avg_vol_20 > 0 else 1
        details['rvol'] = round(rvol, 2)
        price_up = hist['Close'].iloc[-1] > hist['Close'].iloc[-2]
        if rvol >= 2.0 and price_up:
            rvol_score = 8
            reasons.append(f'RVOL {rvol:.1f}x 爆量上漲（高確信，但注意耗盡）')
        elif rvol >= 1.5 and price_up:
            rvol_score = 10
            reasons.append(f'RVOL {rvol:.1f}x 量能確認突破')
        elif rvol >= 1.5 and not price_up:
            rvol_score = -8
            reasons.append(f'RVOL {rvol:.1f}x 放量下跌')
        elif rvol < 1.0 and price_up and momentum_score > 10:
            rvol_score = -3
            reasons.append(f'RVOL {rvol:.1f}x 上漲無量確認')

    # ═══ 衝突懲罰 ═══
    conflict_result = detect_signal_conflicts(details)
    conflict_penalty = conflict_result['penalty']
    if conflict_result['conflicts']:
        reasons.append(f"⚠️ 指標衝突（{len(conflict_result['conflicts'])}項）")
        for c in conflict_result['conflicts']:
            reasons.append(f"  ↳ {c}")
    details['conflicts'] = conflict_result

    # ═══ headline score（純技術面，不含基本面/籌碼）═══
    score = max(-100, min(100, tech_score + connors_rsi_score + rvol_score + conflict_penalty))

    # ═══ 顯示用：基本面與題材分數（不計入 headline score，避免週期污染）═══
    # 中長期基本面由 mid_trend 計分、籌碼由 chip_score 計分；此處僅供前端參考。
    details['fundamental_score'] = _calc_fundamental_display(info, cp)
    details['theme_score'] = _calc_theme_display(info, sector_perf, earnings_days, reasons)

    # ═══ ATR 停損 + 建議部位 ═══
    atr_pct = None
    if 'ATR' in hist.columns and not np.isnan(hist['ATR'].iloc[-1]):
        atr_val = hist['ATR'].iloc[-1]
        details['atr'] = round(atr_val, 2)
        details['atr_stop'] = round(cp - 2 * atr_val, 2)
        atr_pct = atr_val / cp if cp > 0 else None
        today_range = hist['High'].iloc[-1] - hist['Low'].iloc[-1]
        if atr_val > 0 and today_range / atr_val > 2.0:
            reasons.append(f"⚠️ 今日波幅異常大（{today_range / atr_val:.1f}x ATR）")

    confidence = calc_signal_confidence(hist, score)
    details['confidence'] = confidence
    details['position'] = _position_size(
        score, confidence['stability'], atr_pct, regime['caution_mult']
    )

    # ═══ 信號等級 ═══
    if score >= 70:
        signal, signal_color = "📈 強勢做多", "#22c55e"
        action = "多指標共振，技術面強勢，可分批佈局"
    elif score >= 50:
        signal, signal_color = "📈 偏多", "#4ade80"
        action = "信號偏多，可考慮分批建倉"
    elif score >= 30:
        signal, signal_color = "📊 低接留意", "#06b6d4"
        action = "出現底部回升訊號，可開始關注"
    elif score <= -30:
        signal, signal_color = "📉 弱勢離場", "#f87171"
        action = "短線風險高，建議降低曝險"
    elif score <= -15:
        signal, signal_color = "📉 偏弱", "#fb923c"
        action = "頂部訊號浮現，可先減碼"
    else:
        signal, signal_color = "➡️ 中性觀望", "#94a3b8"
        action = "訊號不明確，等待更好機會"

    return {
        'signal': signal,
        'signal_color': signal_color,
        'score': score,
        'action': action,
        'reasons': reasons,
        'details': details,
    }


# ── 顯示用輔助（不計入 headline score）──────────────────────────
def _calc_fundamental_display(info, cp):
    """中長期基本面參考分（±20）。營收/獲利/分析師——僅供前端，不污染短線分數。"""
    if info is None:
        return 0
    s = 0
    rg = info.get('revenueGrowth')
    eg = info.get('earningsGrowth')
    gm = info.get('grossMargins')
    rec = info.get('recommendationMean')
    tgt = info.get('targetMeanPrice')
    upside = (tgt / cp - 1) * 100 if tgt and cp > 0 else None
    if rg is not None:
        s += 13 if rg > 0.50 else 8 if rg > 0.20 else (-8 if rg < -0.05 else 0)
    if eg is not None:
        s += 7 if eg > 0.20 else (-7 if eg < -0.20 else 0)
    if gm is not None and gm > 0.50:
        s += 3
    if rec is not None:
        s += 5 if rec < 2.0 else (-8 if rec > 3.5 else 0)
    if upside is not None:
        s += 5 if upside > 20 else (-8 if upside < -10 else 0)
    return max(-20, min(20, s))


def _calc_theme_display(info, sector_perf, earnings_days, reasons):
    """題材/事件參考分（±15）。財報日 + 板塊輪動。
    註：空單軋空「不」在此計分——軋空由 chip_score 單一負責，避免重複計分。"""
    s = 0
    if earnings_days is not None:
        if 1 <= earnings_days <= 7:
            s -= 5
            reasons.append(f"財報前 {earnings_days} 天，不確定性高")
        elif -3 <= earnings_days <= 0:
            s += 3
            reasons.append("財報剛公佈，資訊透明")
    if sector_perf and isinstance(sector_perf, dict):
        mp = sector_perf.get('1M', {})
        diff = mp.get('diff', 0) if isinstance(mp, dict) else 0
        if diff > 5:
            s += 5
            reasons.append(f"板塊月超額 +{diff:.1f}%")
        elif diff < -5:
            s -= 5
            reasons.append(f"板塊月落後 {diff:.1f}%")
    return max(-15, min(15, s))
