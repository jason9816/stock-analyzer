// 美股/台股主頁行為（AI 分析、分類過濾、背景更新輪詢）
// market 由模板透過 window.PAGE 傳入
function aiAnalyze(sym) {
  var pwd = prompt('輸入 AI 分析密碼：');
  if (!pwd) return;
  var safeId = sym.replace(/\./g, '_');
  var market = (window.PAGE && window.PAGE.market) || '';
  var btn = document.getElementById('ai-btn-'+safeId);
  var box = document.getElementById('ai-box-'+safeId);
  btn.disabled = true;
  btn.textContent = '⏳ 分析中...';
  box.innerHTML = '<span style="color:#64748b;">AI 正在讀取新聞和技術面...</span>';
  box.style.display = 'block';
  fetch('/api/news_summary?symbol='+encodeURIComponent(sym)+'&pwd='+encodeURIComponent(pwd)+'&market='+market)
    .then(function(r){return r.json()})
    .then(function(d){
      if (d.ok) {
        box.textContent = d.summary;
        box.style.display = 'block';
      } else {
        box.innerHTML = '<span style="color:#f87171;">❌ '+d.error+'</span>';
        if (d.error === '密碼錯誤') {}
      }
      btn.disabled = false;
      btn.textContent = '🤖 AI 分析';
    })
    .catch(function(e){
      box.innerHTML = '<span style="color:#f87171;">❌ 連線失敗</span>';
      btn.disabled = false;
      btn.textContent = '🤖 AI 分析';
    });
}
function aiMarket() {
  var pwd = prompt('輸入 AI 分析密碼：');
  if (!pwd) return;
  var btn = document.getElementById('market-ai-btn');
  var box = document.getElementById('market-ai-box');
  var timeEl = document.getElementById('market-ai-time');
  btn.disabled = true;
  btn.textContent = '⏳ 分析中...';
  box.innerHTML = '<span style="color:#64748b;">AI 正在分析大盤環境...</span>';
  box.style.display = 'block';
  fetch('/api/market_summary?pwd='+encodeURIComponent(pwd))
    .then(function(r){return r.json()})
    .then(function(d){
      if (d.ok) {
        box.textContent = d.summary;
        timeEl.textContent = '更新於 ' + d.time;
      } else {
        box.innerHTML = '<span style="color:#f87171;">❌ '+d.error+'</span>';
        if (d.error === '密碼錯誤') {}
      }
      btn.disabled = false;
      btn.textContent = '🤖 大盤 AI 分析';
    })
    .catch(function(e){
      box.innerHTML = '<span style="color:#f87171;">❌ 連線失敗</span>';
      btn.disabled = false;
      btn.textContent = '🤖 大盤 AI 分析';
    });
}
function filterCategory(cat) {
  document.querySelectorAll('.cat-btn').forEach(function(b) {
    b.style.background = '#1e293b';
    b.style.color = '#94a3b8';
    b.style.borderColor = '#334155';
  });
  var btn = document.getElementById('cat-' + cat);
  if (btn) {
    btn.style.background = '#3b82f6';
    btn.style.color = '#fff';
    btn.style.borderColor = '#3b82f6';
  }
  document.querySelectorAll('.stock-card').forEach(function(card) {
    if (cat === 'all' || card.dataset.category === cat) {
      card.style.display = '';
    } else {
      card.style.display = 'none';
    }
  });
}

(function(){
  var market = (window.PAGE && window.PAGE.market) || '';
  var statusEl = document.getElementById('update-status');
  var spinnerEl = document.getElementById('update-spinner');
  var countsEl = document.getElementById('update-counts');
  var lastFullUpdates = 0;
  var lastPriceUpdates = 0;

  function checkStatus() {
    fetch('/api/worker-status?market=' + market)
      .then(function(r) { return r.json(); })
      .then(function(s) {
        if (!s.running) {
          spinnerEl.style.display = 'none';
          statusEl.textContent = '⏸ 背景更新未啟動';
          return;
        }

        // 更新快取計數
        if (countsEl) {
          countsEl.textContent = s.cached + '/' + s.total + ' 已快取｜報價 #' + s.price_updates + '｜完整 #' + s.full_updates;
        }

        // 完整分析優先顯示（較重要），其次快速報價，兩者皆閒置才顯示已更新
        if (s.full_mode === 'full' || s.full_mode === 'history') {
          spinnerEl.style.display = 'inline-block';
          var names = (s.full_current || '').replace(/\.TW/g,'').replace(/\.TWO/g,'');
          statusEl.textContent = '🔄 完整分析：' + names + '（剩 ' + s.remaining + ' 支）';
        } else if (s.price_mode === 'price') {
          spinnerEl.style.display = 'inline-block';
          var names = (s.price_current || '').replace(/\.TW/g,'').replace(/\.TWO/g,'');
          statusEl.textContent = '⚡ ' + names;
        } else {
          spinnerEl.style.display = 'none';
          if (s.last_updated) {
            statusEl.textContent = '✅ 即時更新中（' + s.last_updated + '）';
          }
        }

        // 完整分析輪次增加 → 刷新頁面（有新的基本面/籌碼數據）
        if (s.full_updates > lastFullUpdates && lastFullUpdates > 0) {
          location.reload();
        }
        lastFullUpdates = s.full_updates;

        // 每 3 次報價更新刷新一次頁面（讓價格/指標顯示最新）
        if (s.price_updates > lastPriceUpdates && s.price_updates % 3 === 0 && lastPriceUpdates > 0) {
          location.reload();
        }
        lastPriceUpdates = s.price_updates;
      })
      .catch(function() {
        spinnerEl.style.display = 'none';
        statusEl.textContent = '❌ 連線錯誤';
      });
  }

  // 每 10 秒查詢一次
  setInterval(checkStatus, 10000);
  setTimeout(checkStatus, 2000);
})();
