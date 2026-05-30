# 股票技術分析系統

美股 / 台股技術分析儀表板，含即時報價、多維度評分（短線信號、中線趨勢、籌碼面）、
AI 新聞摘要、Alpaca 模擬交易，以及一套可擴充的策略追蹤框架。

所有功能都能用 `.env` 開關，密鑰也放 `.env`，方便依需求啟用。

---

## 功能總覽

| 功能 | 開關（.env） | 說明 |
|------|-------------|------|
| 美股追蹤 `/` | `ENABLE_US_MARKET` | 美股技術分析、K 線、評分 |
| 台股追蹤 `/tw` | `ENABLE_TW_MARKET` | 台股（TWSE 即時報價）|
| AI 摘要 | `ENABLE_AI_ANALYSIS` | Gemini 個股/大盤分析（需 API key）|
| 模擬交易 `/trading` | `ENABLE_TRADING` | Alpaca paper trading（需 key）|
| 策略追蹤 | `ENABLE_STRATEGY` | 可擴充策略框架（附範例策略）|
| Telegram bot | `ENABLE_TELEGRAM_BOT` | 可擴充的 Telegram bot 範本（需 token）|
| 背景更新 | `ENABLE_BG_WORKERS` | 自動更新報價與分析 |

預設只開美股 / 台股 / AI，其餘關閉 —— 填好金鑰再開即可。

---

## 架設步驟（Windows）

> 需先安裝 [Python 3.10+](https://www.python.org/downloads/)（安裝時勾選 **Add Python to PATH**）。

```bat
:: 1. 下載專案
git clone <你的 repo 網址>
cd stock-analyzer

:: 2. 建立虛擬環境並啟用
python -m venv venv
venv\Scripts\activate

:: 3. 安裝套件
pip install -r requirements.txt

:: 4. 建立設定檔（複製範本後填入金鑰）
copy .env.example .env
notepad .env

:: 5. 啟動
python run.py
```

啟動後開瀏覽器到 **http://localhost:5000**。

> macOS / Linux 把上面第 2 步改成 `python3 -m venv venv && source venv/bin/activate`，
> 第 4 步改成 `cp .env.example .env`。

---

## 設定 `.env`

最少只要能跑美股 / 台股，不填任何金鑰也行（AI 摘要會停用）。
想用 AI 分析就填 `GEMINI_API_KEYS`（[免費申請](https://aistudio.google.com/apikey)）。
各欄位說明都寫在 `.env.example` 裡。

---

## 選用功能的額外需求

- **AI 摘要 / 題材研究**：`GEMINI_API_KEYS`（逗號分隔可多把，自動輪替）
- **模擬交易**：`ALPACA_PAPER_KEY` / `ALPACA_PAPER_SECRET`（[Alpaca paper](https://app.alpaca.markets/paper/dashboard)）+ `ENABLE_TRADING=true`
- **PDF 研究報告**：需 node 套件 `npm install -g md-to-pdf`
- **對外存取**：`TUNNEL_PROVIDER=ngrok` + `NGROK_AUTHTOKEN`（預設 `none` 純本地）

---

## 想改評分演算法？

本系統把「資料抓取 / 前後端」與「分數計算邏輯」分開。
要調整選股邏輯，**只改 `core/` 裡的檔案，前後端完全不用動**。
詳見 [ARCHITECTURE.md](ARCHITECTURE.md)。

---

## 常見問題

**Q: 第一次開沒有資料？**
背景 worker 會自動抓，稍等 1–2 分鐘刷新；或點股票旁的 🔄 手動更新。

**Q: 報價有延遲？**
美股 yfinance 約延遲 15 分鐘；台股用 TWSE 即時。

**Q: 資料存哪？**
`stock_data.json` / `tw_data.json`（自動生成，已被 git 忽略，不會上傳）。
