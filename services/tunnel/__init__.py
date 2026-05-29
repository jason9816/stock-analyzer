"""
對外導出（可抽換）—— 把本地 Flask 服務公開到外網。

統一介面 open_tunnel(port) -> public_url | None，依 config.TUNNEL_PROVIDER 切換。
要新增一種導出方式，就在 services/tunnel/ 底下加一個 <provider>.py 並實作
open(port: int) -> str | None，再到 _PROVIDERS 註冊即可。app.py 與前後端都不用動。

目前內建：
  - none   純本地，只能 localhost 存取（預設）
  - ngrok  用 ngrok 通道（免費版含每月流量限制；本實作支援多 token 自動輪替與固定 dev domain）
"""

from config import TUNNEL_PROVIDER
from services.tunnel import ngrok as _ngrok

# provider 名稱 → 模組（每個模組都提供 open(port) → public_url | None）
_PROVIDERS = {
    'ngrok': _ngrok.open,
}


def open_tunnel(port):
    """依設定開啟對外通道，回傳 public_url；none 或失敗時回傳 None（純本地）。"""
    provider = (TUNNEL_PROVIDER or 'none').lower()
    if provider == 'none':
        return None
    fn = _PROVIDERS.get(provider)
    if not fn:
        print(f'⚠️ 未知的 TUNNEL_PROVIDER: {provider}（支援 {list(_PROVIDERS)} 或 none）')
        return None
    try:
        url = fn(port)
        if url:
            print(f' * 對外通道（{provider}）: {url}')
        return url
    except Exception as e:
        print(f'⚠️ 開啟對外通道失敗（{provider}）: {e}')
        return None
