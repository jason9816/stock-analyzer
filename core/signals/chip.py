def calc_chip_score(
    inst_own,
    short_pct,
    pcr,
    beta,
    short_ratio=0,
    rsi=50,
    macd_hist_val=0,
    insider_score=0,
    analyst_score=0,
):
    """
    籌碼評分 -100 ~ +100（升級版 — 7 維度）

    新增維度：
    - Days to Cover (short_ratio) + 軋空偵測
    - 內部人交易信號 (insider_score)
    - PCR 極端反轉邏輯
    - SI + Insider 交互（Shin & Yoon, 2024）
    - 分析師 EPS Revision（PEAD：Ball & Brown 1968 等）

    Parameters:
        inst_own: 機構持股 %
        short_pct: 空單佔流通股 %
        pcr: Put/Call Ratio
        beta: 波動係數
        short_ratio: Days to Cover (= Short Interest / Avg Daily Volume)
        rsi: RSI（用於軋空偵測）
        macd_hist_val: MACD 柱（用於軋空偵測）
        insider_score: 內部人交易分數（由 calc_insider_score 算出）
        analyst_score: 分析師修正分數（由 calc_analyst_revision_score 算出）
    """
    score = 0
    details = []

    # ── ① 機構持股（±20）──
    if inst_own > 80:
        score += 20
        details.append(f'機構持股 {inst_own}% 極高（大型基金重倉）')
    elif inst_own > 60:
        score += 12
        details.append(f'機構持股 {inst_own}%（法人認可）')
    elif inst_own > 40:
        score += 5
    else:
        score -= 10
        details.append(f'機構持股 {inst_own}% 偏低（流動性風險）')

    # ── ② 空單 + DTC + 軋空偵測（±25）──
    # 基礎空單分
    if short_pct < 3:
        si_score = 15
    elif short_pct < 5:
        si_score = 8
    elif short_pct < 10:
        si_score = -5
        details.append(f'空單 {short_pct}% 偏高')
    elif short_pct < 20:
        si_score = -15
        details.append(f'空單 {short_pct}% 高（看空情緒重）')
    else:
        si_score = -20
        details.append(f'空單 {short_pct}% 極高')

    # DTC (Days to Cover) 加成
    # 高空單看空（扣分）來源：Desai et al. (2002) "An Investigation of the
    #   Informational Role of Short Interest in the Nasdaq Market",
    #   J.Finance 57(5):2263-2287 — https://doi.org/10.1111/0022-1082.00495
    #   高空單股月異常報酬 −0.76%~−1.13%，空單比例越高越看空。
    # DTC（Days-to-Cover）本身的預測力：Hong et al. (2015) "Days to Cover and
    #   Stock Returns", NBER w21166 — https://www.nber.org/papers/w21166
    # 註：下方「軋空 +20/+15」為自家啟發式（高空單+超賣+動能翻正=回補潛力），
    #     上述文獻未直接證實軋空正報酬，門檻待自家回測校準。
    squeeze_flag = False
    if short_ratio > 8:
        si_score -= 5  # 空頭很擁擠
        details.append(f'DTC {short_ratio:.1f} 天（空頭擁擠）')
        # 軋空偵測：高 DTC + 超賣 + MACD 翻正 = 軋空潛力
        if short_pct > 10 and rsi < 40 and macd_hist_val > 0:
            squeeze_flag = True
            si_score += 20  # 翻正！軋空機會
            details.append('🚀 軋空潛力：高空單 + 超賣 + 動能翻正')
    elif short_ratio > 5:
        si_score -= 2
        if short_pct > 15 and rsi < 35:
            squeeze_flag = True
            si_score += 15
            details.append('🚀 軋空留意：高空單 + 技術面超賣')

    score += max(-25, min(25, si_score))

    # ── ③ PCR 含極端反轉（±15）──
    # 來源：Pan & Poteshman (2006) "The Information in Option Volume for Future
    #   Stock Prices", RFS 19(3):871-908 — https://doi.org/10.1093/rfs/hhj024
    # 註：Pan & Poteshman 發現「低 PCR 股票隔日跑贏」（PCR 偏資訊性），
    #     此處把極端 PCR 當反向情緒指標用，機制方向不完全相同，解讀須留意。
    if 0.5 <= pcr <= 0.8:
        score += 15
    elif 0.4 <= pcr < 0.5:
        score += 5  # 樂觀但接近過熱
    elif pcr < 0.4:
        score -= 3  # 極度樂觀 = 反向警告
        details.append(f'PCR {pcr} 極低（過度樂觀，留意反轉）')
    elif 0.8 < pcr <= 1.0:
        score -= 3
    elif 1.0 < pcr <= 1.2:
        score -= 8
    elif pcr > 1.5:
        score += 5  # 極度恐慌 = 反向底部信號
        details.append(f'PCR {pcr} 極高（極度恐慌 → 反向買入機會）')
    elif pcr > 1.2:
        score -= 15
        details.append(f'PCR {pcr} 高（避險情緒重）')

    # ── ④ Beta（±5）──
    if beta < 1.0:
        score += 5
    elif beta < 1.2:
        score += 3
    elif beta > 2.0:
        score -= 5
        details.append(f'Beta {beta} 極高波動')
    elif beta > 1.5:
        score -= 3

    # ── ⑤ 內部人交易（±15）── 來源：Lakonishok & Lee (2001), Kang et al. (2018)
    score += max(-15, min(15, insider_score))

    # ── SI + Insider 交互 ──
    # 來源：Shin & Yoon (2024) "Does Short Selling Regulate Insider Trading?",
    #   Korean J. of Financial Studies — https://doi.org/10.26845/KJFS.2024.08.53.4.421
    #   放空者與內部人在負面資訊上競爭，放空者會壓抑內部人買入訊號的獲利
    #   → 高空單時內部人買入的可靠度下降，故扣分。
    if insider_score > 5 and short_pct > 15:
        score -= 5  # 扣分：戰場股
        details.append('⚠️ 內部人買 vs 高空單 = 對峙股（信號衝突）')
    elif insider_score > 5 and short_pct < 5:
        score += 3  # 加分：共識看多
        details.append('✅ 內部人買 + 低空單 = 共識看多')

    # ── ⑥ 軋空額外加成（±10）──
    if squeeze_flag:
        score += 10

    # ── ⑦ 分析師 EPS Revision（±15）──
    # 來源（盈餘公告後漂移 PEAD / 分析師修正動量）：
    #   Ball & Brown (1968) J.Acct.Research — https://doi.org/10.2307/2490232
    #   Givoly & Lakonishok (1979) J.Acct.&Econ — https://doi.org/10.1016/0165-4101(79)90006-5
    score += max(-15, min(15, analyst_score))

    return max(-100, min(100, score)), details, squeeze_flag


def calc_insider_score(ticker_obj, market_cap=None):
    """
    Enhanced insider trading signal
    - Filters option exercises (non-informative)
    - Weights by dollar amount (>$100K = high conviction)
    - Small-cap boost (<$2B market cap = 1.5x)

    來源：
    - Lakonishok & Lee (2001) "Are Insider Trades Informative?", RFS 14(1):79-111
      https://doi.org/10.1093/rfs/14.1.79
      重內部人「買入」具預測力、賣出幾乎無；買入組合 12 個月超額報酬高出賣出組
      約 7.8%（控制 size/B-M 後約 4.8%），且小型股效果遠強於大型股 → 故小型股加成。
    - Kang, Kim & Wang (2018) "Cluster Trading of Corporate Insiders", JCF
      https://doi.org/10.1016/j.jcorpfin.2018.08.012
      多位內部人同向買入（cluster）資訊量更強：21 日異常報酬約 3.8% vs 非群聚 2%
      （近兩倍），90 日差距更大 → 故多人同買給予高分加成。

    Returns: (score, description)
    """
    try:
        insider = ticker_obj.insider_transactions
        if insider is None or insider.empty:
            return 0, ''

        recent = insider.head(20)  # More transactions for better signal
        buys = 0
        big_buys = 0  # > $100K
        sells = 0
        for _, row in recent.iterrows():
            text = str(row.get('Text', '') or row.get('text', '')).lower()
            value = abs(row.get('Value', 0) or 0)

            # Filter: skip option exercises (non-informative per 2025 research)
            if any(kw in text for kw in ['option', 'exercise', 'conversion', 'award']):
                continue

            if 'purchase' in text or 'buy' in text:
                buys += 1
                if value > 100000:
                    big_buys += 1
            elif 'sale' in text or 'sell' in text:
                sells += 1

        score = 0
        note = ''
        # Big purchases are 2x more informative (academic consensus 2025)
        if big_buys >= 2:
            score = 15
            note = f'\U0001f525 {big_buys} 筆大額買入 (>$100K) — 高確信度'
        elif big_buys >= 1:
            score = 10
            note = '大額內部人買入 (>$100K)'
        elif buys >= 3:
            score = 12
            note = f'\U0001f525 內部人密集買入（{buys} 筆）'
        elif buys >= 2:
            score = 8
            note = f'內部人買入 {buys} 筆'
        elif buys >= 1 and sells <= 1:
            score = 5
            note = f'內部人買入 {buys} 筆'

        if sells >= 5 and buys == 0:
            score = -10
            note = f'\u26a0\ufe0f 內部人密集賣出（{sells} 筆）'
        elif sells >= 3 and buys == 0:
            score = -5
            note = f'內部人賣出 {sells} 筆'

        # Small-cap boost: insider signal is 1.5x stronger in small caps
        if market_cap and market_cap < 2e9 and score > 0:
            score = int(score * 1.5)
            note += '（小型股加成）'
        elif market_cap and market_cap < 10e9 and score > 0:
            score = int(score * 1.2)

        return max(-15, min(15, score)), note
    except Exception:
        return 0, ''


def calc_analyst_revision_score(ticker_obj):
    """
    分析師 EPS Revision 動量 — 學術最強基本面信號
    來源：Post-Earnings Announcement Drift (PEAD), 2024-2025

    Returns: (score: int, note: str)
    """
    score = 0
    notes = []

    try:
        # 1. EPS Revisions (last 30 days)
        revisions = ticker_obj.get_eps_revisions()
        if revisions is not None and not revisions.empty:
            for period in ['0q', '+1q']:
                if period in revisions.columns:
                    up_30 = (
                        revisions.loc['upLast30days', period]
                        if 'upLast30days' in revisions.index
                        else 0
                    )
                    down_30 = (
                        revisions.loc['downLast30days', period]
                        if 'downLast30days' in revisions.index
                        else 0
                    )
                    up_30 = up_30 or 0
                    down_30 = down_30 or 0

                    if up_30 > 0 and down_30 == 0:
                        score += 8
                        notes.append(f'EPS 上修 {int(up_30)} 筆')
                    elif up_30 > down_30 * 2 and up_30 > 0:
                        score += 4
                    elif down_30 > up_30 * 2 and down_30 > 0:
                        score -= 4
                    elif down_30 > 0 and up_30 == 0:
                        score -= 8
                        notes.append(f'EPS 下修 {int(down_30)} 筆')
                    break  # Only use nearest quarter
    except Exception:
        pass

    try:
        # 2. Recent upgrades/downgrades
        ud = ticker_obj.get_upgrades_downgrades()
        if ud is not None and not ud.empty:
            recent = ud.tail(10)
            ups = 0
            downs = 0
            for _, row in recent.iterrows():
                action = str(row.get('Action', '') or row.get('action', '')).lower()
                if action in ['upgrade', 'up', 'initiated', 'init']:
                    ups += 1
                elif action in ['downgrade', 'down']:
                    downs += 1

            if ups > downs + 2:
                score += 5
                notes.append(f'分析師偏多 ({ups}升/{downs}降)')
            elif downs > ups + 2:
                score -= 5
                notes.append(f'分析師偏空 ({downs}降/{ups}升)')
    except Exception:
        pass

    return max(-15, min(15, score)), '；'.join(notes)


def chip_label(score, squeeze_flag=False):
    if squeeze_flag:
        return "🚀 軋空潛力", "#a78bfa"
    if score >= 40:
        return "🟢 籌碼強勢", "#22c55e"
    elif score >= 20:
        return "🟢 籌碼偏多", "#4ade80"
    elif score >= 0:
        return "➡️ 籌碼中性", "#94a3b8"  # Was yellow, now gray
    elif score >= -20:
        return "📉 籌碼偏弱", "#fb923c"  # Was yellow, now orange
    else:
        return "🔴 籌碼偏空", "#f87171"
