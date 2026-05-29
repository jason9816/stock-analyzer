"""
ngrok tunnel provider —— 多 token 自動輪替 + 固定 dev domain。

設定（.env）：
  NGROK_AUTHTOKENS   多把 token 逗號分隔；任一把流量爆（ERR_NGROK_725）會自動切下一把
  NGROK_DOMAINS      與 NGROK_AUTHTOKENS 一一對應的免費 dev domain（沒填就用隨機網址）
"""

import time

from config import NGROK_AUTHTOKENS, NGROK_DOMAINS

# ngrok 流量爆 / 帳號限制的錯誤碼（只認專屬錯誤碼，避免誤判 502 等正常錯誤頁）
_QUOTA_MARKERS = (
    'ERR_NGROK_3200',  # tunnel quota exceeded
    'ERR_NGROK_108',  # account limit reached
    'ERR_NGROK_725',  # network bandwidth limit reached
    'ERR_NGROK_8012',
    'reached its network bandwidth limit',  # quota 頁的專屬字串
)


def _contains_quota_marker(text):
    text = (text or '').lower()
    return any(m.lower() in text for m in _QUOTA_MARKERS)


def _probe_quota(url):
    """
    對 ngrok URL 自己打一次確認沒爆量。
    流量爆時 ngrok 邊緣直接回 HTTP 403 + body 含 ERR_NGROK_725。
    其他狀態（502 backend unreachable / 200 正常）一律當沒爆量。
    """
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={'ngrok-skip-browser-warning': '1'})
        urllib.request.urlopen(req, timeout=10).read(1024)
        return False
    except urllib.error.HTTPError as e:
        if e.code != 403:
            return False  # 502/503/504 等是本機 backend 沒起，不是流量爆
        try:
            body = e.read(8192).decode('utf-8', errors='ignore')
        except Exception:
            body = ''
        return _contains_quota_marker(body)
    except Exception:
        return False


def open(port):
    """
    依序試 NGROK_AUTHTOKENS 各把 token，碰到流量爆就換下一把。
    若該 token 在 NGROK_DOMAINS 有對應 domain，網址就會固定不變。
    """
    try:
        from pyngrok import conf, ngrok
    except ImportError:
        print('⚠️ TUNNEL_PROVIDER=ngrok 但未安裝 pyngrok（pip install pyngrok）')
        return None

    tokens = list(NGROK_AUTHTOKENS) or [None]  # 沒填 token 也試一次（pyngrok 會用系統設定）
    last_err = None
    for i, token in enumerate(tokens, start=1):
        # 殺掉前一輪殘留的 ngrok process，避免換 token 後仍用舊認證
        try:
            ngrok.kill()
        except Exception:
            pass
        time.sleep(2)  # 等 ngrok process 真的死透，否則 token 換了沒生效
        if token:
            conf.get_default().auth_token = token
        # 若有對應的固定 domain，connect 時指定，網址就永遠不變
        domain = NGROK_DOMAINS[i - 1] if i - 1 < len(NGROK_DOMAINS) else None
        try:
            if domain:
                url = ngrok.connect(port, domain=domain).public_url
            else:
                url = ngrok.connect(port).public_url
        except Exception as e:
            last_err = e
            if _contains_quota_marker(str(e)) and i < len(tokens):
                print(f'⚠️ ngrok token #{i} 流量已滿，改用 #{i + 1}')
                continue
            print(f'⚠️ ngrok 開啟失敗（token #{i}）: {str(e)[:200]}')
            return None

        # tunnel 開起來了，但要 self-probe 才能確認沒爆量
        if _probe_quota(url):
            print(f'⚠️ ngrok token #{i} 流量已滿（self-probe ERR_NGROK_725），換下一把')
            if i < len(tokens):
                continue
            print('⚠️ 所有 ngrok token 流量都已滿')
            return None

        if len(tokens) > 1:
            print(f'   （ngrok 使用第 {i}/{len(tokens)} 把 token）')
        return url

    print(f'⚠️ 所有 ngrok token 都失敗: {str(last_err)[:200]}')
    return None
