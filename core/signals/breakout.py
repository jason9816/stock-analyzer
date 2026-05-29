import numpy as np


# ── 起漲前評分系統（v1）──────────────────────────────────
def calc_prebreakout_score(hist):
    """
    起漲前特徵評分 -100 ~ +100
    布林收窄 + MACD 負柱收斂 + RSI 低位回升 + 價格貼近 MA20 + 量能變化 + 底部墊高
    回測驗證：≥80 分 → 10天勝率 60.5%、Alpha +1.43%
    """
    if len(hist) < 30:
        return 0, []
    i = len(hist) - 1
    score = 0
    reasons = []
    cp = hist['Close'].iloc[i]
    ma20 = hist['MA20'].iloc[i]
    ma50 = (
        hist['MA60'].iloc[i]
        if 'MA60' in hist.columns and not np.isnan(hist['MA60'].iloc[i])
        else hist['MA20'].iloc[i]
    )
    rsi = hist['RSI'].iloc[i]
    rsi_prev = hist['RSI'].iloc[i - 1]
    mh = hist['MACD_hist'].iloc[i]
    mhp = hist['MACD_hist'].iloc[i - 1]
    ml = hist['MACD'].iloc[i]
    ms = hist['MACD_signal'].iloc[i]
    mlp = hist['MACD'].iloc[i - 1]
    msp = hist['MACD_signal'].iloc[i - 1]
    bbu = hist['BB_upper'].iloc[i]
    bbl = hist['BB_lower'].iloc[i]
    bbm = hist['BB_mid'].iloc[i]

    # 1. 布林帶收窄（改善 #3：向量化計算，效能提升 50x+）
    bb_w = (bbu - bbl) / bbm * 100 if bbm > 0 else 99
    recent_hist = hist.iloc[max(0, i - 60) : i + 1]
    bb_ws_series = (
        (recent_hist['BB_upper'] - recent_hist['BB_lower'])
        / recent_hist['BB_mid'].replace(0, np.nan)
        * 100
    )
    bb_ws_series = bb_ws_series.dropna()
    bb_pct = (bb_ws_series > bb_w).mean() * 100 if len(bb_ws_series) > 0 else 50
    if bb_pct >= 85:
        score += 25
        reasons.append(f"布林帶極度收窄（近60天最窄{100 - bb_pct:.0f}%），即將變盤")
    elif bb_pct >= 70:
        score += 15
        reasons.append("布林帶收窄中，波動壓縮蓄勢")
    elif bb_pct >= 55:
        score += 8

    # 2. MACD 負值收斂 / 即將金叉
    if mh < 0 and mh > mhp:
        score += 15
        reasons.append("MACD 負柱持續縮小，空頭力道衰退")
        if i >= 3 and hist['MACD_hist'].iloc[i - 2] < mhp:
            score += 10
            reasons.append("MACD 柱連續 3 天收斂")
        if ml > ms * 0.95 and ml < ms:
            score += 12
            reasons.append("⚡ MACD 即將金叉")
    if ml > ms and mlp <= msp:
        score += 15
        reasons.append("⚡ MACD 剛發生金叉")
    elif i >= 2 and hist['MACD'].iloc[i - 2] <= hist['MACD_signal'].iloc[i - 2] and ml > ms:
        score += 10
        reasons.append("MACD 金叉確認中（第2天）")

    # 3. RSI 低位回升
    if 40 <= rsi <= 55 and rsi > rsi_prev:
        score += 12
        reasons.append(f"RSI {rsi:.0f} 溫和回升，動能轉正")
    elif 30 <= rsi < 40 and rsi > rsi_prev:
        score += 18
        reasons.append(f"RSI {rsi:.0f} 從超賣區回升，反彈空間大")
    elif rsi > 65:
        score -= 20
    elif rsi > 55:
        score -= 5

    # 4. 價格位置：貼近 MA20
    d20 = (cp / ma20 - 1) * 100
    d50 = (cp / ma50 - 1) * 100
    if abs(d20) <= 3 and d50 > 0:
        score += 18
        reasons.append("價格貼近 MA20 整理，MA60 支撐在下")
    elif abs(d20) <= 3:
        score += 10
        reasons.append("價格在 MA20 附近整理")
    elif d20 > 8:
        score -= 15
    elif d20 < -5:
        score -= 10

    # MA20 斜率
    ma20_slope = (ma20 - hist['MA20'].iloc[i - 5]) / hist['MA20'].iloc[i - 5] * 100
    if 0 <= ma20_slope <= 2:
        score += 10
        reasons.append("MA20 走平或微升，底部打底完成")
    elif ma20_slope > 2:
        score += 5
    elif ma20_slope < -1:
        score -= 8

    # 5. 量能：縮量整理 + 近期放量信號
    vol_ma = hist['Volume'].rolling(20).mean().iloc[i]
    rv = hist['Volume'].iloc[i - 4 : i + 1].mean()
    pv = hist['Volume'].iloc[i - 15 : i - 5].mean() if i >= 15 else vol_ma
    v3 = hist['Volume'].iloc[i - 2 : i + 1].values
    spike = any(v > vol_ma * 1.3 for v in v3)
    if rv < pv * 0.8 and not spike:
        score += 8
        reasons.append("縮量整理中，等待放量突破")
    if spike and cp > hist['Close'].iloc[i - 3]:
        score += 15
        reasons.append("近3天出現放量上漲，主力進場訊號")

    # 6. 底部墊高
    if i >= 19:
        rl = hist['Low'].iloc[i - 9 : i + 1].min()
        pl = hist['Low'].iloc[i - 19 : i - 9].min()
        if rl > pl:
            score += 10
            reasons.append("底部墊高，低點越來越高")

    # 7. 排除已大漲
    if i >= 20:
        r20 = (cp / hist['Close'].iloc[i - 20] - 1) * 100
        if r20 > 15:
            score -= 25
        elif r20 > 8:
            score -= 10
        elif -5 <= r20 <= 3:
            score += 5

    return max(-100, min(100, score)), reasons


# ── support/resistance levels ────────────────────────────
def calc_levels(hist, current_price):
    """計算多層支撐壓力位"""
    levels = []
    ma5 = hist['MA5'].iloc[-1]
    ma10 = hist['MA10'].iloc[-1]
    ma20 = hist['MA20'].iloc[-1]
    ma60 = hist['MA60'].iloc[-1] if not np.isnan(hist['MA60'].iloc[-1]) else None

    # MA levels
    for name, val in [('MA5', ma5), ('MA10', ma10), ('MA20', ma20), ('MA60', ma60)]:
        if val is None or np.isnan(val):
            continue
        dist = (val / current_price - 1) * 100
        levels.append(
            {
                'price': round(val, 2),
                'type': f'{name}位置',
                'dist': round(dist, 1),
                'kind': 'P' if val > current_price else 'S',
            }
        )

    # Recent highs/lows
    for days, label in [(22, '近月'), (60, '近季')]:
        seg = hist.tail(days)
        h = seg['High'].max()
        l = seg['Low'].min()
        if h > current_price:
            levels.append(
                {
                    'price': round(h, 2),
                    'type': f'{label}最高',
                    'dist': round((h / current_price - 1) * 100, 1),
                    'kind': 'P',
                }
            )
        if l < current_price:
            levels.append(
                {
                    'price': round(l, 2),
                    'type': f'{label}最低',
                    'dist': round((l / current_price - 1) * 100, 1),
                    'kind': 'S',
                }
            )

    # Bollinger — 根據與現價的相對位置決定壓力/支撐
    bb_upper = hist['BB_upper'].iloc[-1]
    bb_lower = hist['BB_lower'].iloc[-1]
    if not np.isnan(bb_upper):
        kind = 'P' if bb_upper > current_price else 'S'
        levels.append(
            {
                'price': round(bb_upper, 2),
                'type': '布林上軌',
                'dist': round((bb_upper / current_price - 1) * 100, 1),
                'kind': kind,
            }
        )
    if not np.isnan(bb_lower):
        kind = 'P' if bb_lower > current_price else 'S'
        levels.append(
            {
                'price': round(bb_lower, 2),
                'type': '布林下軌',
                'dist': round((bb_lower / current_price - 1) * 100, 1),
                'kind': kind,
            }
        )

    # 52w
    return levels
