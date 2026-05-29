def calc_candle_pattern(hist):
    """
    K 線形態辨識 — 分析最近 1-3 根 K 線
    回傳: dict with pattern name, bias (bullish/bearish/neutral), score, description
    """
    o = hist['Open'].iloc[-1]
    h = hist['High'].iloc[-1]
    l = hist['Low'].iloc[-1]
    c = hist['Close'].iloc[-1]

    body = abs(c - o)
    total = h - l
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l
    is_bullish = c > o  # 紅K

    patterns = []
    score = 0

    if total == 0:
        return {
            'patterns': [],
            'score': 0,
            'details': {'body': 0, 'upper_shadow': 0, 'lower_shadow': 0, 'total': 0},
        }

    body_ratio = body / total
    upper_ratio = upper_shadow / total
    lower_ratio = lower_shadow / total

    # ── 單根 K 線形態 ──

    # K 線形態加入位置上下文（同型態在不同趨勢位置含義不同）
    # 來源：Caginalp & Laurent (1998) "The Predictive Power of Price Patterns",
    #   Applied Mathematical Finance 5(3-4):181-205 —
    #   https://doi.org/10.1080/135048698334637
    #   證實 K 線型態須在「趨勢脈絡」下才具統計顯著性。
    # 反面對照：Marshall et al. (2006) JBF 多數型態無顯著獲利
    #   https://doi.org/10.1016/j.jbankfin.2005.08.001 → K 線宜低權重輔助。
    # 錘子線在跌勢末端才偏多；射擊之星在漲勢末端才偏空
    trend_20d = 0
    if len(hist) >= 20:
        close_20d_ago = hist['Close'].iloc[-20]
        if close_20d_ago > 0:
            trend_20d = (c / close_20d_ago - 1) * 100  # 20天漲跌幅百分比

    # 長下影線（錘子/倒T）: 下影 > 實體×2，且上影短
    if lower_shadow > body * 2 and upper_ratio < 0.2:
        if trend_20d < -8:  # 下跌超 8% 後出現 = 強止跌
            score += 25
            patterns.append("🔨 錘子線（跌勢中出現）— 強力止跌信號")
        elif trend_20d > 8:  # 漲勢中出現 = 力道減弱
            score += 5
            patterns.append("🔨 長下影線（漲勢中出現）— 僅小幅偏多")
        else:
            score += 15
            if is_bullish:
                patterns.append("🔨 錘子線（長下影紅K）— 止跌信號")
            else:
                patterns.append("🔨 上吊線（長下影黑K）— 下方有承接")

    # 長上影線（射擊之星）: 上影 > 實體×2，且下影短
    elif upper_shadow > body * 2 and lower_ratio < 0.2:
        if trend_20d > 8:  # 上漲超 8% 後出現 = 強反壓
            score -= 25
            patterns.append("🌠 射擊之星（漲勢末端）— 強力反壓信號")
        elif trend_20d < -8:  # 跌勢中出現 = 可能只是震盪
            score -= 5
            patterns.append("🌠 長上影線（跌勢中出現）— 僅小幅偏空")
        else:
            score -= 15
            if not is_bullish:
                patterns.append("🌠 射擊之星（長上影黑K）— 反壓信號")
            else:
                patterns.append("🌠 長上影紅K — 上方壓力重")

    # 十字線: 實體極小
    elif body_ratio < 0.1:
        patterns.append("✝️ 十字線 — 多空角力，方向不明")
        # 看位置判斷意義
        if lower_ratio > 0.6:
            patterns.append("  → 蜻蜓十字（長下影）= 偏多")
            score += 10
        elif upper_ratio > 0.6:
            patterns.append("  → 墓碑十字（長上影）= 偏空")
            score -= 10

    # 大陽線 (實體佔比 > 70%, 紅K)
    elif body_ratio > 0.7 and is_bullish:
        patterns.append("📈 大陽線 — 多方強勢")
        score += 15

    # 大陰線 (實體佔比 > 70%, 黑K)
    elif body_ratio > 0.7 and not is_bullish:
        patterns.append("📉 大陰線 — 空方強勢")
        score -= 15

    # ── 兩根 K 線組合 ──
    if len(hist) >= 2:
        o2 = hist['Open'].iloc[-2]
        h2 = hist['High'].iloc[-2]
        l2 = hist['Low'].iloc[-2]
        c2 = hist['Close'].iloc[-2]
        is_bullish2 = c2 > o2

        # 多頭吞噬: 前黑後紅，紅K完全包住前一根
        if not is_bullish2 and is_bullish and c > o2 and o < c2:
            patterns.append("🐂 多頭吞噬 — 底部反轉信號")
            score += 18

        # 空頭吞噬: 前紅後黑，黑K完全包住前一根
        elif is_bullish2 and not is_bullish and o > c2 and c < o2:
            patterns.append("🐻 空頭吞噬 — 頭部反轉信號")
            score -= 18

        # 跳空上漲
        if l > h2:
            patterns.append("⬆️ 跳空上漲缺口")
            score += 10

        # 跳空下跌
        elif h < l2:
            patterns.append("⬇️ 跳空下跌缺口")
            score -= 10

    # ── 三根 K 線組合 ──
    if len(hist) >= 3:
        o3 = hist['Open'].iloc[-3]
        c3 = hist['Close'].iloc[-3]
        is_bullish3 = c3 > o3

        # 晨星: 前大陰 + 小實體(十字) + 大陽
        body3 = abs(c3 - o3)
        body2_curr = abs(hist['Close'].iloc[-2] - hist['Open'].iloc[-2])
        if (
            not is_bullish3
            and body3 > total * 0.3
            and body2_curr < body3 * 0.3
            and is_bullish
            and body > total * 0.3
        ):
            patterns.append("⭐ 晨星 — 底部強反轉信號")
            score += 22

        # 夜星: 前大陽 + 小實體 + 大陰
        if (
            is_bullish3
            and body3 > total * 0.3
            and body2_curr < body3 * 0.3
            and not is_bullish
            and body > total * 0.3
        ):
            patterns.append("🌙 夜星 — 頭部強反轉信號")
            score -= 22

        # 紅三兵
        if (
            hist['Close'].iloc[-3] > hist['Open'].iloc[-3]
            and hist['Close'].iloc[-2] > hist['Open'].iloc[-2]
            and c > o
            and hist['Close'].iloc[-2] > hist['Close'].iloc[-3]
            and c > hist['Close'].iloc[-2]
        ):
            patterns.append("🔴🔴🔴 紅三兵 — 連續上攻")
            score += 12

        # 黑三兵
        if (
            hist['Close'].iloc[-3] < hist['Open'].iloc[-3]
            and hist['Close'].iloc[-2] < hist['Open'].iloc[-2]
            and c < o
            and hist['Close'].iloc[-2] < hist['Close'].iloc[-3]
            and c < hist['Close'].iloc[-2]
        ):
            patterns.append("⚫⚫⚫ 黑三兵 — 連續下殺")
            score -= 12

    # ── 量 + K 線組合判斷 ──
    vol_today = hist['Volume'].iloc[-1]
    vol_ma20 = hist['Volume'].tail(20).mean()
    vol_ratio = vol_today / vol_ma20 if vol_ma20 > 0 else 1

    vol_candle = None
    if vol_ratio > 2.0:  # 爆量 (2倍以上)
        if lower_shadow > body * 1.5 and lower_ratio > 0.4:
            vol_candle = "💥 爆量長下影 — 主力大量承接，強力止跌"
            score += 20
        elif upper_shadow > body * 1.5 and upper_ratio > 0.4:
            vol_candle = "💥 爆量長上影 — 大量出貨，頭部確認"
            score -= 20
        elif is_bullish and body_ratio > 0.6:
            vol_candle = "💥 爆量長紅 — 突破信號，多方強攻"
            score += 15
        elif not is_bullish and body_ratio > 0.6:
            vol_candle = "💥 爆量長黑 — 恐慌賣壓，破位下殺"
            score -= 15
    elif vol_ratio > 1.5:
        if is_bullish and body_ratio > 0.5:
            vol_candle = "📊 量增紅K — 買盤積極"
            score += 8
        elif not is_bullish and body_ratio > 0.5:
            vol_candle = "📊 量增黑K — 賣壓加重"
            score -= 8

    return {
        'patterns': patterns,
        'vol_candle': vol_candle,
        'score': max(-50, min(50, score)),
        'details': {
            'body': round(body, 2),
            'upper_shadow': round(upper_shadow, 2),
            'lower_shadow': round(lower_shadow, 2),
            'total': round(total, 2),
            'body_ratio': round(body_ratio * 100, 1),
            'upper_ratio': round(upper_ratio * 100, 1),
            'lower_ratio': round(lower_ratio * 100, 1),
            'is_bullish': is_bullish,
            'vol_ratio': round(vol_ratio, 2),
        },
    }
