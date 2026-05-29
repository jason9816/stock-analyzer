// 共用前端工具 —— 所有頁面透過 base.html 載入
(function () {
  'use strict';

  // 輕量 toast 通知
  let toastTimer = null;
  window.toast = function (msg, kind) {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = msg;
    el.style.borderColor =
      kind === 'error' ? 'var(--color-down)' : kind === 'ok' ? 'var(--color-up)' : 'var(--border-default)';
    el.style.display = 'block';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.style.display = 'none'; }, 3200);
  };

  // POST JSON 包裝，回傳 parsed JSON（失敗丟出 Error）
  window.postJSON = async function (url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.error) throw new Error(data.error || ('HTTP ' + r.status));
    return data;
  };
})();
