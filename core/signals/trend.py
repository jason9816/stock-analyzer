import numpy as np


# ══════════════════════════════════════════════════════════════
# 中期趨勢評分系統 (2-8 週)
# 來源：Weinstein Stage Analysis + Minervini SEPA + IBD RS + 學術動量研究
# 六維度評分：MA排列 + 相對強度 + ADX趨勢 + 量能確認 + 動量 + 趨勢品質
# ══════════════════════════════════════════════════════════════
def calc_mid_trend(hist, index_hist=None, w52h=None, w52l=None):
    """
    中期趨勢評分 -100 ~ +100

    Parameters:
        hist: 個股歷史資料 DataFrame（需含 Close, High, Low, Volume, OBV, ADX, DI_plus, DI_minus）
        index_hist: S&P500 (或加權指數) 歷史收盤價 Series（用於 RS 計算）
        w52h: 52 週最高價（可選，沒給就自己算）
        w52l: 52 週最低價（可選）

    Returns:
        dict with score, stage, components, label, color, advice, minervini_pass, etc.
    """
    if len(hist) < 60:
        return {
            'score': 0,
            'stage': 'N/A',
            'stage_label': '⚪ 數據不足',
            'minervini_pass': 0,
            'minervini_total': 8,
            'rs_vs_benchmark': 0,
            'trend_quality': 0,
            'components': {},
            'label': '⚪ 數據不足',
            'color': '#94a3b8',
            'advice': '歷史數據不足 60 天，無法判定中期趨勢',
        }

    cp = hist['Close'].iloc[-1]
    closes = hist['Close']
    highs = hist['High']
    lows = hist['Low']
    volumes = hist['Volume']

    # ── 計算所需的均線 ──
    ema20 = closes.ewm(span=20).mean().iloc[-1]
    sma50 = closes.rolling(50).mean().iloc[-1] if len(hist) >= 50 else ema20
    sma150 = closes.rolling(150).mean().iloc[-1] if len(hist) >= 150 else np.nan
    sma200 = closes.rolling(200).mean().iloc[-1] if len(hist) >= 200 else np.nan

    # 52 週高低（從參數或自己算）
    if w52h is None or w52l is None:
        lookback_252 = min(252, len(hist))
        w52h = highs.tail(lookback_252).max()
        w52l = lows.tail(lookback_252).min()

    # ══════════════════════════════════════════════════════════
    # Component 1：MA 排列 + 斜率（滿分 ±30）
    # 來源：Minervini SEPA + Weinstein 30-week SMA 斜率
    # ══════════════════════════════════════════════════════════
    ma_score = 0
    ma_reasons = []

    # 排列檢查（每對正確 = +5 或 -5）
    pairs = []
    if not np.isnan(ema20):
        pairs.append(('Price > EMA20', cp > ema20))
    if not np.isnan(sma50):
        pairs.append(('EMA20 > SMA50', ema20 > sma50))
    if not np.isnan(sma150) and not np.isnan(sma50):
        pairs.append(('SMA50 > SMA150', sma50 > sma150))
    if not np.isnan(sma150) and not np.isnan(sma200):
        pairs.append(('SMA150 > SMA200', sma150 > sma200))

    bullish_count = sum(1 for _, ok in pairs if ok)
    bearish_count = sum(1 for _, ok in pairs if not ok)

    if len(pairs) > 0:
        # 滿分按比例：4 對全對 = +20
        ma_score = int((bullish_count - bearish_count) / len(pairs) * 20)

    # 斜率加分（SMA50 斜率）
    if len(hist) >= 55 and not np.isnan(sma50):
        sma50_5ago = closes.rolling(50).mean().iloc[-6] if len(hist) >= 56 else sma50
        sma50_slope = (sma50 / sma50_5ago - 1) * 100 if sma50_5ago > 0 else 0
        if sma50_slope > 0.5:
            ma_score += 5
            ma_reasons.append(f'SMA50 上升中（斜率 +{sma50_slope:.1f}%）')
        elif sma50_slope > 0:
            ma_score += 2
        elif sma50_slope < -0.5:
            ma_score -= 5
            ma_reasons.append(f'SMA50 下降中（斜率 {sma50_slope:.1f}%）')
        elif sma50_slope < 0:
            ma_score -= 2

    # SMA200 趨勢（Minervini 要求上升至少 1 個月）
    if len(hist) >= 222 and not np.isnan(sma200):
        sma200_22ago = closes.rolling(200).mean().iloc[-23]
        if not np.isnan(sma200_22ago) and sma200 > sma200_22ago:
            ma_score += 5
            ma_reasons.append('SMA200 過去一個月上升 ✓')
        elif not np.isnan(sma200_22ago) and sma200 < sma200_22ago:
            ma_score -= 5

    ma_score = max(-30, min(30, ma_score))

    # 排列描述
    if bullish_count == len(pairs) and len(pairs) >= 3:
        ma_reasons.insert(0, '均線完美多頭排列 ✓')
    elif bearish_count == len(pairs) and len(pairs) >= 3:
        ma_reasons.insert(0, '均線完全空頭排列 ✗')
    elif bullish_count > bearish_count:
        ma_reasons.insert(0, f'均線偏多排列（{bullish_count}/{len(pairs)}）')
    else:
        ma_reasons.insert(0, f'均線偏空排列（{bearish_count}/{len(pairs)} 對反轉）')

    # ══════════════════════════════════════════════════════════
    # Component 2：相對強度 RS（滿分 ±20）
    # 來源：IBD RS Rating + Mansfield RS
    # Mansfield RS: MRS = ((RS_ratio / SMA(RS_ratio, 252)) - 1) * 100
    # MRS > 0 = outperforming, MRS rising = accelerating outperformance
    # ══════════════════════════════════════════════════════════
    rs_score = 0
    rs_value = 0
    rs_reasons = []

    if index_hist is not None and len(index_hist) >= 63:
        # Mansfield RS: normalized to its own history
        # Build aligned price ratio series
        try:
            # Align stock and index by date overlap
            stock_close = closes.astype(float)
            benchmark_close = index_hist.astype(float)
            rs_ratio = stock_close / benchmark_close.reindex(stock_close.index, method='ffill')
            rs_ratio = rs_ratio.dropna()
            if len(rs_ratio) >= 20:
                rs_sma_period = min(len(rs_ratio), 252)
                rs_sma = rs_ratio.rolling(rs_sma_period).mean()
                if rs_sma.iloc[-1] > 0:
                    mansfield_rs = ((rs_ratio.iloc[-1] / rs_sma.iloc[-1]) - 1) * 100
                else:
                    mansfield_rs = 0
                rs_value = round(mansfield_rs, 1)

                if mansfield_rs > 10:
                    rs_score = 20
                    rs_reasons.append(f'Mansfield RS +{mansfield_rs:.1f} 大幅跑贏大盤')
                elif mansfield_rs > 5:
                    rs_score = 15
                    rs_reasons.append(f'Mansfield RS +{mansfield_rs:.1f} 跑贏大盤')
                elif mansfield_rs > 2:
                    rs_score = 8
                    rs_reasons.append(f'Mansfield RS +{mansfield_rs:.1f} 略贏大盤')
                elif mansfield_rs > 0:
                    rs_score = 3
                elif mansfield_rs > -3:
                    rs_score = -3
                elif mansfield_rs > -8:
                    rs_score = -10
                    rs_reasons.append(f'Mansfield RS {mansfield_rs:.1f} 跑輸大盤')
                else:
                    rs_score = -20
                    rs_reasons.append(f'Mansfield RS {mansfield_rs:.1f} 大幅跑輸大盤')
            else:
                # Fallback to simple excess return
                stock_roc_63 = (
                    (cp / closes.iloc[-min(63, len(closes))] - 1) * 100 if len(closes) >= 63 else 0
                )
                idx_63 = (
                    index_hist.iloc[-1] / index_hist.iloc[-min(63, len(index_hist))] - 1
                ) * 100
                excess_3m = stock_roc_63 - idx_63
                rs_value = round(excess_3m, 1)
                if excess_3m > 15:
                    rs_score = 20
                elif excess_3m > 8:
                    rs_score = 15
                elif excess_3m > 3:
                    rs_score = 8
                elif excess_3m > 0:
                    rs_score = 3
                elif excess_3m > -5:
                    rs_score = -3
                elif excess_3m > -10:
                    rs_score = -10
                else:
                    rs_score = -20
                rs_reasons.append(f'3 個月超額報酬 {excess_3m:.1f}%（簡易 RS）')
        except Exception:
            # Fallback to simple excess return on alignment failure
            stock_roc_63 = (
                (cp / closes.iloc[-min(63, len(closes))] - 1) * 100 if len(closes) >= 63 else 0
            )
            idx_63 = (index_hist.iloc[-1] / index_hist.iloc[-min(63, len(index_hist))] - 1) * 100
            excess_3m = stock_roc_63 - idx_63
            rs_value = round(excess_3m, 1)
            if excess_3m > 15:
                rs_score = 20
            elif excess_3m > 8:
                rs_score = 15
            elif excess_3m > 3:
                rs_score = 8
            elif excess_3m > 0:
                rs_score = 3
            elif excess_3m > -5:
                rs_score = -3
            elif excess_3m > -10:
                rs_score = -10
            else:
                rs_score = -20
            rs_reasons.append(f'3 個月超額報酬 {excess_3m:.1f}%（fallback）')
    else:
        rs_reasons.append('無大盤數據，略過 RS 計算')

    # ══════════════════════════════════════════════════════════
    # Component 3：ADX 趨勢強度 + 方向（滿分 ±15）
    # ══════════════════════════════════════════════════════════
    adx_score = 0
    adx_reasons = []

    if 'ADX' in hist.columns and not np.isnan(hist['ADX'].iloc[-1]):
        adx_val = hist['ADX'].iloc[-1]
        di_p = hist['DI_plus'].iloc[-1]
        di_m = hist['DI_minus'].iloc[-1]
        bullish_dir = di_p > di_m

        if adx_val > 30:
            adx_score = 15 if bullish_dir else -15
            adx_reasons.append(
                f'ADX {adx_val:.0f} 強趨勢，DI{"+ 領先" if bullish_dir else "- 領先（空方）"}'
            )
        elif adx_val > 25:
            adx_score = 10 if bullish_dir else -10
            adx_reasons.append(f'ADX {adx_val:.0f} 中等趨勢')
        elif adx_val > 20:
            adx_score = 5 if bullish_dir else -5
            adx_reasons.append(f'ADX {adx_val:.0f} 趨勢形成中')
        else:
            adx_score = 0
            adx_reasons.append(f'ADX {adx_val:.0f} 盤整（無趨勢）')

        # ADX 斜率加分
        if len(hist) >= 6:
            adx_prev = hist['ADX'].iloc[-6]
            if not np.isnan(adx_prev):
                if adx_val > adx_prev + 3:
                    adx_score += 3 if bullish_dir else -3
                    adx_reasons.append('ADX 上升中（趨勢增強）')
                elif adx_val < adx_prev - 3:
                    adx_reasons.append('ADX 下降中（趨勢減弱）')

    adx_score = max(-15, min(15, adx_score))

    # ══════════════════════════════════════════════════════════
    # Component 4：量能確認（滿分 ±15）
    # 來源：Weinstein 量能確認 + OBV 趨勢
    # ══════════════════════════════════════════════════════════
    vol_score = 0
    vol_reasons = []

    # OBV 趨勢 vs 價格趨勢
    if 'OBV' in hist.columns and len(hist) >= 20:
        obv = hist['OBV']
        obv_slope = obv.iloc[-1] - obv.iloc[-20]  # 20 天 OBV 變化
        price_slope = closes.iloc[-1] - closes.iloc[-20]  # 20 天價格變化

        if price_slope > 0 and obv_slope > 0:
            vol_score += 8
            vol_reasons.append('OBV 與價格同步上升（量能確認）')
        elif price_slope > 0 and obv_slope < 0:
            vol_score -= 8
            vol_reasons.append('⚠️ OBV 頂背離：價漲量縮')
        elif price_slope < 0 and obv_slope > 0:
            vol_score += 5
            vol_reasons.append('OBV 底背離：量能暗中累積')
        elif price_slope < 0 and obv_slope < 0:
            vol_score -= 5

    # 近期量能變化
    if len(hist) >= 60:
        vol_20 = volumes.tail(20).mean()
        vol_60 = volumes.tail(60).mean()
        vol_ratio = vol_20 / vol_60 if vol_60 > 0 else 1

        if vol_ratio > 1.3 and closes.iloc[-1] > closes.iloc[-20]:
            vol_score += 7
            vol_reasons.append(f'近 20 天量能擴張（量比 {vol_ratio:.1f}x）+ 價漲')
        elif vol_ratio > 1.3 and closes.iloc[-1] < closes.iloc[-20]:
            vol_score -= 7
            vol_reasons.append(f'近 20 天放量下跌（量比 {vol_ratio:.1f}x）')
        elif vol_ratio < 0.6 and closes.iloc[-1] > closes.iloc[-20]:
            vol_score -= 3
            vol_reasons.append('量價背離：價漲但量能萎縮')

    vol_score = max(-15, min(15, vol_score))

    # ══════════════════════════════════════════════════════════
    # Component 5：動量 ROC（滿分 ±10）
    # 來源：學術共識 — ROC(21) + ROC(63) 組合
    # ══════════════════════════════════════════════════════════
    mom_score = 0
    mom_reasons = []

    roc_21 = (cp / closes.iloc[-min(21, len(closes))] - 1) * 100 if len(closes) >= 21 else 0
    roc_63 = (cp / closes.iloc[-min(63, len(closes))] - 1) * 100 if len(closes) >= 63 else 0
    combined_roc = roc_21 * 0.6 + roc_63 * 0.4

    if combined_roc > 15:
        mom_score = 10
        mom_reasons.append(f'強動量（ROC21: +{roc_21:.1f}%, ROC63: +{roc_63:.1f}%）')
    elif combined_roc > 8:
        mom_score = 7
    elif combined_roc > 3:
        mom_score = 4
        mom_reasons.append(f'溫和動量（ROC21: +{roc_21:.1f}%）')
    elif combined_roc > 0:
        mom_score = 2
    elif combined_roc > -5:
        mom_score = -3
    elif combined_roc > -10:
        mom_score = -6
        mom_reasons.append(f'動量轉弱（ROC21: {roc_21:.1f}%）')
    else:
        mom_score = -10
        mom_reasons.append(f'動量大幅下滑（ROC21: {roc_21:.1f}%, ROC63: {roc_63:.1f}%）')

    # ══════════════════════════════════════════════════════════
    # Component 6：趨勢品質 Q-Indicator + Efficiency Ratio（滿分 ±10）
    # 來源：量化基金 Trend Quality + Kaufman Efficiency Ratio
    # ══════════════════════════════════════════════════════════
    tq_score = 0
    tq_value = 0
    tq_reasons = []

    lookback_tq = min(50, len(hist) - 1)
    q_indicator = 0
    efficiency_ratio = 0
    if lookback_tq >= 20:
        net_move = abs(closes.iloc[-1] - closes.iloc[-lookback_tq])
        total_path = sum(
            abs(closes.iloc[-lookback_tq + i + 1] - closes.iloc[-lookback_tq + i])
            for i in range(lookback_tq - 1)
        )
        q_indicator = net_move / total_path if total_path > 0 else 0

        # Efficiency Ratio (Kaufman): |net change| / sum(|daily changes|)
        # ER ≈ 1 = perfect trend, ER ≈ 0 = choppy
        er_period = min(60, len(closes) - 1)
        if er_period > 10:
            net_change = abs(closes.iloc[-1] - closes.iloc[-er_period])
            sum_changes = closes.diff().abs().iloc[-er_period:].sum()
            efficiency_ratio = net_change / sum_changes if sum_changes > 0 else 0
        else:
            efficiency_ratio = 0

        # Combine Q-indicator and Efficiency Ratio (average)
        trend_quality = (q_indicator + efficiency_ratio) / 2
        tq_value = round(trend_quality, 3)

        # 上漲天數比例
        bullish_days = sum(
            1 for i in range(-lookback_tq + 1, 0) if closes.iloc[i] > closes.iloc[i - 1]
        )
        bullish_pct = bullish_days / (lookback_tq - 1) * 100

        # 趨勢方向
        trend_dir = 1 if closes.iloc[-1] > closes.iloc[-lookback_tq] else -1

        if trend_quality > 0.15:
            tq_score = 8 * trend_dir
            tq_reasons.append(f'趨勢品質高（Q={q_indicator:.2f}, ER={efficiency_ratio:.2f}）')
        elif trend_quality > 0.08:
            tq_score = 4 * trend_dir
        elif trend_quality < 0.03:
            tq_score = -3  # 震盪市 = 略扣
            tq_reasons.append(f'趨勢品質低（Q={q_indicator:.2f}, ER={efficiency_ratio:.2f}）')

        if bullish_pct > 60:
            tq_score += 2
        elif bullish_pct < 40:
            tq_score -= 2

    tq_score = max(-10, min(10, tq_score))

    # ══════════════════════════════════════════════════════════
    # Weinstein Stage 判定
    # ══════════════════════════════════════════════════════════
    stage = _detect_weinstein_stage(cp, sma150, sma200, w52h, w52l, hist)

    # Volume confirmation for Stage 2 (2025 research)
    # Stage 2 breakout is more reliable with RVOL > 1.5
    stage_details = {}
    if stage['stage'] == 'Stage 2' and len(volumes) > 20:
        recent_vol = volumes.iloc[-5:].mean()
        avg_vol = volumes.iloc[-20:].mean()
        stage_rvol = recent_vol / avg_vol if avg_vol > 0 else 1
        if stage_rvol > 1.5:
            stage_details['stage_volume'] = f'量能確認 (RVOL {stage_rvol:.1f}x)'
        elif stage_rvol < 0.7:
            stage_details['stage_volume'] = f'量能偏弱 (RVOL {stage_rvol:.1f}x)'
            # Weak volume undermines Stage 2 reliability
            # Applied as minor penalty in vol_score area

    # ══════════════════════════════════════════════════════════
    # Minervini SEPA 8 項檢查
    # ══════════════════════════════════════════════════════════
    minervini = _check_minervini_template(cp, ema20, sma50, sma150, sma200, w52h, w52l, hist)

    # ══════════════════════════════════════════════════════════
    # Stage 2 volume penalty (TASK 8)
    # ══════════════════════════════════════════════════════════
    stage_vol_penalty = 0
    if stage['stage'] == 'Stage 2' and len(volumes) > 20:
        recent_vol_s2 = volumes.iloc[-5:].mean()
        avg_vol_s2 = volumes.iloc[-20:].mean()
        stage_rvol_s2 = recent_vol_s2 / avg_vol_s2 if avg_vol_s2 > 0 else 1
        if stage_rvol_s2 < 0.7:
            stage_vol_penalty = -3  # Weak volume undermines stage
            tq_reasons.append(f'Stage 2 量能偏弱 (RVOL {stage_rvol_s2:.1f}x)')

    # ══════════════════════════════════════════════════════════
    # 綜合評分
    # ══════════════════════════════════════════════════════════
    total = ma_score + rs_score + adx_score + vol_score + mom_score + tq_score + stage_vol_penalty
    score = max(-100, min(100, total))

    # 匯總原因
    all_reasons = ma_reasons + rs_reasons + adx_reasons + vol_reasons + mom_reasons + tq_reasons

    # 標籤 + 建議
    if score >= 60:
        label = '🟢 中線強勢'
        color = '#22c55e'
        advice = '中期趨勢明確向上，回檔是加碼機會。持股續抱，跌到 EMA20 可考慮加碼。'
    elif score >= 30:
        label = '🟢 中線偏多'
        color = '#4ade80'
        advice = '中期趨勢偏多，可持有或逢低佈局。注意量能是否跟上。'
    elif score >= 10:
        label = '🟡 中線觀望'
        color = '#fbbf24'
        advice = '趨勢不明確，等方向確認。突破 SMA50 做多，跌破 SMA200 離場。'
    elif score >= -10:
        label = '⚪ 中線中性'
        color = '#94a3b8'
        advice = '多空拉鋸，等待方向出來再操作。'
    elif score >= -30:
        label = '🟡 中線偏空'
        color = '#fb923c'
        advice = '中期趨勢轉弱，減碼或觀望。不建議新建多倉。'
    else:
        label = '🔴 中線空頭'
        color = '#f87171'
        advice = '中期趨勢向下，不適合做多。等趨勢反轉再進場。'

    return {
        'score': score,
        'stage': stage['stage'],
        'stage_label': stage['label'],
        'stage_desc': stage.get('desc', ''),
        'stage_details': stage_details,
        'minervini_pass': minervini['pass_count'],
        'minervini_total': 8,
        'minervini_details': minervini['details'],
        'rs_vs_benchmark': rs_value,
        'trend_quality': tq_value,
        'roc_21': round(roc_21, 1),
        'roc_63': round(roc_63, 1),
        'components': {
            'ma_alignment': ma_score,
            'relative_strength': rs_score,
            'adx_trend': adx_score,
            'volume_confirm': vol_score,
            'momentum': mom_score,
            'trend_quality': tq_score,
        },
        'reasons': all_reasons,
        'label': label,
        'color': color,
        'advice': advice,
    }


def _detect_weinstein_stage(cp, sma150, sma200, w52h, w52l, hist):
    """
    Weinstein Stage 1-4 自動判定
    基於 30-week SMA (≈150-day) 的斜率和價格相對位置
    """
    if np.isnan(sma150) if isinstance(sma150, float) else True:
        # 沒有足夠數據算 SMA150
        if len(hist) >= 50:
            sma50 = hist['Close'].rolling(50).mean().iloc[-1]
            if cp > sma50:
                return {
                    'stage': 'Stage 2?',
                    'label': '📈 可能上升（數據不足確認）',
                    'desc': 'SMA150 不足，用 SMA50 替代判斷',
                }
            else:
                return {
                    'stage': 'Stage 4?',
                    'label': '📉 可能下降（數據不足確認）',
                    'desc': 'SMA150 不足，用 SMA50 替代判斷',
                }
        return {'stage': 'N/A', 'label': '⚪ 數據不足', 'desc': ''}

    # SMA150 斜率（過去 22 天的變化）
    if len(hist) >= 172:
        sma150_22ago = hist['Close'].rolling(150).mean().iloc[-23]
        sma150_slope = (
            (sma150 / sma150_22ago - 1) * 100
            if not np.isnan(sma150_22ago) and sma150_22ago > 0
            else 0
        )
    else:
        sma150_slope = 0

    pct_from_high = (cp / w52h - 1) * 100 if w52h > 0 else 0
    pct_from_low = (cp / w52l - 1) * 100 if w52l > 0 else 0

    if sma150_slope < -0.3:
        if cp < sma150:
            return {
                'stage': 'Stage 4',
                'label': '📉 下跌趨勢（Stage 4）',
                'desc': f'SMA150 下降中，股價在均線下方。距高點 {pct_from_high:.0f}%。不適合做多。',
            }
        else:
            return {
                'stage': 'Stage 1',
                'label': '🔄 底部打底（Stage 1）',
                'desc': 'SMA150 仍下降但股價已站上。可能正在築底，等 SMA150 走平確認。',
            }
    elif abs(sma150_slope) <= 0.3:
        # 走平
        if cp > sma150 * 1.05:
            return {
                'stage': 'Stage 3',
                'label': '⚠️ 做頭階段（Stage 3）',
                'desc': 'SMA150 走平，股價在上方但動能減弱。注意是否跌破 SMA150。',
            }
        elif cp < sma150 * 0.95:
            return {
                'stage': 'Stage 1',
                'label': '🔄 底部打底（Stage 1）',
                'desc': 'SMA150 走平，股價在下方。築底中，等突破 SMA150 確認 Stage 2。',
            }
        else:
            # 在 SMA150 附近
            return {
                'stage': 'Transition',
                'label': '🔄 轉換期',
                'desc': 'SMA150 走平且價格接近。方向未明，等待突破方向。',
            }
    else:
        # SMA150 上升
        if pct_from_high > -25 and pct_from_low > 25:
            return {
                'stage': 'Stage 2',
                'label': '📈 上升趨勢（Stage 2）',
                'desc': f'SMA150 上升，距高點 {pct_from_high:.0f}%，距低點 +{pct_from_low:.0f}%。理想持有/買入階段。',
            }
        elif pct_from_low > 15:
            return {
                'stage': 'Stage 2 Early',
                'label': '📈 上升初期（Stage 2 Early）',
                'desc': f'SMA150 開始上升，距低點 +{pct_from_low:.0f}%。趨勢形成中。',
            }
        else:
            return {
                'stage': 'Stage 2?',
                'label': '📈 可能上升（待確認）',
                'desc': 'SMA150 上升但漲幅有限，需確認突破力道。',
            }


def _check_minervini_template(cp, ema20, sma50, sma150, sma200, w52h, w52l, hist):
    """
    Minervini SEPA 趨勢模板 — 8 項嚴格篩選
    全部通過 = 頂尖趨勢股候選
    """
    checks = []

    # 1. Price > SMA50
    if not np.isnan(sma50):
        ok = cp > sma50
        checks.append({'name': '股價 > SMA50', 'pass': ok, 'value': f'{cp:.2f} vs {sma50:.2f}'})
    else:
        checks.append({'name': '股價 > SMA50', 'pass': False, 'value': '數據不足'})

    # 2. Price > SMA150
    if not np.isnan(sma150):
        ok = cp > sma150
        checks.append({'name': '股價 > SMA150', 'pass': ok, 'value': f'{cp:.2f} vs {sma150:.2f}'})
    else:
        checks.append({'name': '股價 > SMA150', 'pass': False, 'value': '數據不足'})

    # 3. Price > SMA200
    if not np.isnan(sma200):
        ok = cp > sma200
        checks.append({'name': '股價 > SMA200', 'pass': ok, 'value': f'{cp:.2f} vs {sma200:.2f}'})
    else:
        checks.append({'name': '股價 > SMA200', 'pass': False, 'value': '數據不足'})

    # 4. SMA50 > SMA150
    if not np.isnan(sma50) and not np.isnan(sma150):
        ok = sma50 > sma150
        checks.append(
            {'name': 'SMA50 > SMA150', 'pass': ok, 'value': f'{sma50:.2f} vs {sma150:.2f}'}
        )
    else:
        checks.append({'name': 'SMA50 > SMA150', 'pass': False, 'value': '數據不足'})

    # 5. SMA150 > SMA200
    if not np.isnan(sma150) and not np.isnan(sma200):
        ok = sma150 > sma200
        checks.append(
            {'name': 'SMA150 > SMA200', 'pass': ok, 'value': f'{sma150:.2f} vs {sma200:.2f}'}
        )
    else:
        checks.append({'name': 'SMA150 > SMA200', 'pass': False, 'value': '數據不足'})

    # 6. SMA200 上升（過去 1 個月）
    sma200_rising = False
    if len(hist) >= 222:
        sma200_now = hist['Close'].rolling(200).mean().iloc[-1]
        sma200_22ago = hist['Close'].rolling(200).mean().iloc[-23]
        if not np.isnan(sma200_now) and not np.isnan(sma200_22ago):
            sma200_rising = sma200_now > sma200_22ago
    checks.append(
        {
            'name': 'SMA200 上升趨勢',
            'pass': sma200_rising,
            'value': '上升' if sma200_rising else '下降或不足',
        }
    )

    # 7. 股價在 52 週高點 25% 以內
    if w52h > 0:
        pct = cp / w52h
        ok = pct >= 0.75
        checks.append(
            {'name': '距 52 週高 ≤25%', 'pass': ok, 'value': f'{(1 - pct) * 100:.1f}% 距高點'}
        )
    else:
        checks.append({'name': '距 52 週高 ≤25%', 'pass': False, 'value': 'N/A'})

    # 8. 股價比 52 週低點高 30%+
    if w52l > 0:
        pct = cp / w52l
        ok = pct >= 1.30
        checks.append(
            {'name': '距 52 週低 ≥30%', 'pass': ok, 'value': f'+{(pct - 1) * 100:.1f}% 距低點'}
        )
    else:
        checks.append({'name': '距 52 週低 ≥30%', 'pass': False, 'value': 'N/A'})

    pass_count = sum(1 for c in checks if c['pass'])
    return {'pass_count': pass_count, 'details': checks}
