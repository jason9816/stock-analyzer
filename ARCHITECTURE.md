# 架構說明

給想修改邏輯的人（或他的 AI）看的文件。重點：**哪些檔案可以安全修改、改了不會弄壞前後端。**

---

## 資料流

```
yfinance / TWSE          抓原始資料（K線、基本面、籌碼）
      │                  data/fetchers.py, data/tw.py, data/history.py
      ▼
core/indicators.py       算技術指標（RSI/MACD/KD/ADX/布林/OBV...）
      │
      ▼
core/signals/            算分數（swing/trend/chip/pattern/breakout，純函式）
      │
      ▼
core/analysis.py         整合成一支股票的完整分析 dict
      │
      ▼
data/store.py            存進 JSON 快取
      │
      ▼
web/ (blueprints)        Flask 讀快取 → 渲染頁面 / 回 API
      │
      ▼
web/templates/           前端顯示
```

背景 `web/workers.py` 兩個迴圈自動驅動上面流程：快速迴圈（30 秒）更新報價+指標，
慢速迴圈（每小時）跑完整分析。

---

## 目錄職責

| 目錄 | 職責 |
|------|------|
| `config.py` | 密鑰（讀 .env）、功能開關、股票池 |
| `core/` | **演算法核心**：指標 + 評分 + 整合（可抽換）|
| `data/` | 資料抓取與 JSON 儲存 |
| `services/` | 外部服務：Gemini、Alpaca、PDF 報告、對外導出 |
| `strategy/` | 可擴充策略框架：PortfolioTracker + Strategy 介面 + 範例策略 |
| `web/` | Flask app factory + blueprints + 前端 |
| `scripts/` | CLI：Telegram bot 範本 |

---

## 三個可抽換點

改這些地方時，**前後端、blueprint、template 完全不用動** —— 它們只消費輸出，不關心怎麼算的。

### 1. 分數演算法 → `core/signals/`

拆成聚焦的子模組（swing/trend/chip/pattern/breakout），各為純函式：輸入資料、
輸出分數 dict。想換計分方式（調權重、改門檻、加指標）就改這裡：

```python
# 短線信號（-100 ~ +100）
calc_swing_signal(hist, info=None, sector_perf=None, earnings_days=None)
  → {'signal': str, 'score': int, 'action': str, 'reasons': list, 'details': dict}

# 中線趨勢（-100 ~ +100，含 Weinstein Stage / Minervini）
calc_mid_trend(hist, index_hist=None, w52h=None, w52l=None)
  → {'score': int, 'stage': str, 'label': str, 'color': str, 'components': dict, ...}

# 籌碼面（-100 ~ +100，7 維度）
calc_chip_score(inst_own, short_pct, pcr, beta, short_ratio=0, rsi=50,
                macd_hist_val=0, insider_score=0, analyst_score=0)
  → (score: int, details: list, squeeze_flag: bool)
```

`hist` 是含技術指標欄位的 pandas DataFrame（由 `core/analysis.py` 準備好）。
只要回傳的 dict 鍵不變，前端就照常顯示。

### 2. 技術指標 → `core/indicators.py`

`calc_rsi`、`calc_macd`、`calc_kd`、`calc_adx`、`calc_bollinger` 等，都是
`Series → Series` 的純函式。要改指標參數（如 RSI 從 14 改 9）或加新指標就改這裡。

### 3. 對外導出 → `services/tunnel/`

`open_tunnel(port)` 統一介面。要換 ngrok / Cloudflare / 自架，加一個 provider 函式
並註冊到 `_PROVIDERS`，或直接設 `.env` 的 `TUNNEL_PROVIDER`。

---

## 功能開關

`config.FEATURE_FLAGS` 從 `.env` 的 `ENABLE_*` 讀取。`web/__init__.py` 的 `create_app()`
依開關決定註冊哪些 blueprint —— 關掉的功能該網址直接 404，導航列也隱藏。
`run.py` 依開關決定啟動哪些背景 worker 與排程。

---

## 改邏輯的範例

> 「我想讓 RSI > 80 才算超買（原本 70），而且把籌碼面的機構持股權重調高。」

1. 改 `core/signals/swing.py` 的 `calc_swing_signal` 內 RSI 判斷門檻。
2. 改 `core/signals/chip.py` 的 `calc_chip_score` 內機構持股的給分。
3. 存檔、重啟 `python run.py`。完成 —— 不必碰 `web/`、`data/`、template。
