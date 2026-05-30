"""
agy 研究 provider —— 呼叫 agy CLI 做深度瓶頸股研究。

這是 research 的其中一個可抽換 provider（見 services/research/__init__.py）。
要換成 Gemini API / Claude / 其他，照 research(topic) -> (text, candidates) 的
介面另寫一個 provider 並在 __init__ 註冊即可。
"""

import json
import os
import re
import subprocess

from config import AGY_PATH

# 瓶頸投資的研究 prompt（這是「策略觀點」，clone 者可改成自己的選股邏輯）
_PROMPT_TEMPLATE = """你是瓶頸投資分析師。用以下五條件評分系統找出供應鏈瓶頸股。

五條件（每項1-5分，平均≥3.5值得建倉）：
1. 不可替代：市場上幾家能做？5=獨佔, 4=雙寡佔
2. 產能受限：短期能擴產嗎？5=物理限制
3. 需求爆發：YoY成長？5=>100%
4. 新聞未反映：市場是否已知？5=完全沒人討論
5. 股價未反映：估值price in？5=嚴重低估

目標：市值 $500M~$20B，Forward PE < 35
研究領域：{topic}

上網搜尋最新產業動態，找 3-5 支新瓶頸股，每支附代號、瓶頸原因、五條件評分、
Forward PE、市值、催化劑、風險。用繁體中文。最後附 JSON 區塊（```json 包住）：
```json
[{{"symbol":"XXXX","score":4.1,"scores":{{"不可替代":4.5,"產能受限":4.0,"需求爆發":4.5,"新聞未反映":3.5,"股價未反映":3.8}},"reasons":{{"不可替代":"...","產能受限":"...","需求爆發":"...","新聞未反映":"...","股價未反映":"..."}},"forward_pe":"26x","market_cap":"$2.7B","catalyst":"...","risk":"..."}}]
```"""


def _parse_candidates(output: str) -> list:
    """從研究報告的 ```json``` 區塊解析 candidates。"""
    match = re.search(r'```json\s*(\[.*?\])\s*```', output, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return []


def research(topic: str) -> tuple:
    """用 agy CLI 研究題材，回傳 (報告文字, candidates list)。"""
    if not AGY_PATH or not os.path.exists(AGY_PATH):
        return f'❌ 找不到 agy（AGY_PATH={AGY_PATH}）', []

    prompt = _PROMPT_TEMPLATE.format(topic=topic)
    try:
        result = subprocess.run(
            [
                AGY_PATH,
                '--print',
                prompt,
                '--print-timeout',
                '30m',
                '--dangerously-skip-permissions',
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        out = result.stdout or ''
        if len(out) < 100:
            return f'❌ agy 無輸出 (rc={result.returncode}): {(result.stderr or "")[:300]}', []
        # agy 可能把完整報告寫到 brain 檔，從 stdout 的 file:// 連結讀回
        m = re.search(r'file://(/.+?\.md)', out)
        if m:
            try:
                with open(m.group(1), encoding='utf-8') as f:
                    brain = f.read()
                if len(brain) > len(out):
                    out = brain
            except OSError:
                pass
        return out, _parse_candidates(out)
    except subprocess.TimeoutExpired:
        return '⏰ 研究超時（30 分鐘）', []
    except Exception as e:
        return f'❌ 研究失敗：{e}', []
