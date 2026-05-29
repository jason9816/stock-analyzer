function showToast(msg, type) {
  var t = document.getElementById('toast');
  t.style.display = 'block';
  t.style.borderColor = type === 'error' ? '#f87171' : '#4ade80';
  t.innerHTML = msg;
  setTimeout(function(){ t.style.display = 'none'; }, 4000);
}

function submitTrade(side) {
  var symbol = document.getElementById('trade-symbol').value.trim().toUpperCase();
  var qty = parseFloat(document.getElementById('trade-qty').value);
  var type = document.getElementById('trade-type').value;
  var limitPrice = document.getElementById('trade-limit').value;

  if (!symbol || !qty || qty <= 0) {
    showToast('❌ 請輸入股票代號和數量', 'error');
    return;
  }

  var body = { symbol: symbol, qty: qty, type: type };
  if (type === 'limit' && limitPrice) body.limit_price = parseFloat(limitPrice);

  var url = side === 'buy' ? '/api/trading/buy' : '/api/trading/sell';
  var resultEl = document.getElementById('trade-result');
  resultEl.textContent = '⏳ 下單中...';

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.error) {
      showToast('❌ ' + data.error, 'error');
      resultEl.textContent = '❌ ' + data.error;
    } else {
      var msg = (side === 'buy' ? '📈 買入' : '📉 賣出') + ' ' + data.symbol + ' x' + data.qty + ' — ' + data.status;
      showToast('✅ ' + msg, 'success');
      resultEl.textContent = '✅ ' + msg;
      setTimeout(function(){ location.reload(); }, 2000);
    }
  })
  .catch(function(e) {
    showToast('❌ 網路錯誤', 'error');
    resultEl.textContent = '❌ 網路錯誤';
  });
}

function closePosition(symbol) {
  if (!confirm('確定平倉 ' + symbol + '？')) return;
  fetch('/api/trading/close', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol: symbol })
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.error) showToast('❌ ' + data.error, 'error');
    else { showToast('✅ ' + symbol + ' 已平倉', 'success'); setTimeout(function(){ location.reload(); }, 1500); }
  });
}

function cancelOrder(id) {
  fetch('/api/trading/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ order_id: id })
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.error) showToast('❌ ' + data.error, 'error');
    else { showToast('✅ 訂單已取消', 'success'); setTimeout(function(){ location.reload(); }, 1500); }
  });
}

function cancelAll() {
  if (!confirm('確定取消所有未成交訂單？')) return;
  fetch('/api/trading/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ order_id: 'all' })
  })
  .then(function(r) { return r.json(); })
  .then(function() {
    showToast('✅ 所有訂單已取消', 'success');
    setTimeout(function(){ location.reload(); }, 1500);
  });
}

// Auto-refresh every 30s
setInterval(function(){
  fetch('/api/trading/account').then(r => r.json()).then(data => {
    if (data.equity) document.getElementById('equity').textContent = '$' + Number(data.equity).toLocaleString('en-US', {minimumFractionDigits:2});
  }).catch(()=>{});
}, 30000);

// ═══ 策略追蹤 ═══

function scoreColor(s) {
  if (s >= 4.0) return '#4ade80';
  if (s >= 3.5) return '#34d399';
  if (s >= 2.5) return '#fbbf24';
  return '#f87171';
}

function scoreBarWidth(s) { return Math.min(Math.max((s / 5) * 100, 0), 100); }

function fmtPnl(val) {
  return (val >= 0 ? '+' : '') + val.toFixed(2);
}

function loadStrategy() {
  fetch('/api/strategy').then(r => r.json()).then(function(data) {
    var container = document.getElementById('strategy-container');
    var html = '';
    var hasContent = false;

    Object.keys(data).sort().forEach(function(group, idx) {
      var g = data[group];
      var perf = g.performance || {};
      var positions = perf.positions || {};
      var candidates = g.candidates || [];
      var numPos = Object.keys(positions).length;
      if (numPos === 0 && candidates.length === 0) return;
      hasContent = true;

      var pnlPct = perf.total_pnl_pct || 0;
      var pnlCls = pnlPct >= 0 ? 'positive' : 'negative';

      html += '<div class="strat-group" style="animation-delay:' + (idx * 0.08) + 's;">';

      // ── Group Header ──
      html += '<div class="strat-group-head">';
      html += '<div class="strat-group-title">';
      html += '<span class="strat-tag">' + group + '</span>';
      html += g.name;
      html += '</div>';
      html += '<div class="strat-group-stats">';
      html += '<span class="strat-val">$' + (perf.total_value || 0).toLocaleString('en-US', {maximumFractionDigits:0}) + '</span>';
      html += '<span class="pnl-chip ' + pnlCls + '">' + fmtPnl(pnlPct) + '%</span>';
      if (numPos > 0) html += '<span class="strat-val">' + numPos + ' 檔</span>';
      if (candidates.length > 0) html += '<span class="strat-val">' + candidates.length + ' 候選</span>';
      html += '</div></div>';

      // ── Positions ──
      if (numPos > 0) {
        html += '<div class="strat-section-label">持倉</div>';
        html += '<table class="strat-table"><thead><tr>';
        html += '<th>代號</th><th>題材</th><th>數量</th><th>均價</th><th>現價</th><th style="text-align:right;">損益</th>';
        html += '</tr></thead><tbody>';
        Object.keys(positions).forEach(function(sym) {
          var p = positions[sym];
          var pnl = p.pnl || 0;
          var cls = pnl >= 0 ? 'positive' : 'negative';
          html += '<tr>';
          html += '<td class="sym">' + sym + '</td>';
          html += '<td class="theme-tag">' + (p.theme || '') + '</td>';
          html += '<td>' + p.qty + '</td>';
          html += '<td>$' + (p.avg_price || 0).toFixed(2) + '</td>';
          html += '<td>$' + (p.current_price || 0).toFixed(2) + '</td>';
          html += '<td style="text-align:right;"><span class="pnl-chip ' + cls + '">$' + fmtPnl(pnl) + ' (' + fmtPnl(p.pnl_pct || 0) + '%)</span></td>';
          html += '</tr>';
        });
        html += '</tbody></table>';
      }

      // ── Candidates ──
      if (candidates.length > 0) {
        html += '<div class="strat-section-label">候選股</div>';
        html += '<table class="strat-table"><thead><tr>';
        html += '<th>代號</th><th>題材</th><th>瓶頸分</th><th>Fwd PE</th><th>市值</th><th>加入</th><th></th>';
        html += '</tr></thead><tbody>';
        candidates.forEach(function(c) {
          var sc = c.score || 0;
          var col = scoreColor(sc);
          var barW = scoreBarWidth(sc);
          html += '<tr>';
          html += '<td class="sym">' + c.symbol + '</td>';
          html += '<td class="theme-tag">' + (c.theme || '') + '</td>';
          html += '<td><div class="score-cell">';
          html += '<div class="score-bar-bg"><div class="score-bar-fill" style="width:' + barW + '%;background:' + col + ';"></div></div>';
          html += '<span class="score-num" style="color:' + col + ';">' + sc.toFixed(1) + '</span>';
          html += '</div></td>';
          html += '<td>' + (c.forward_pe || '—') + '</td>';
          html += '<td>' + (c.market_cap || '—') + '</td>';
          html += '<td class="theme-tag">' + (c.date || '') + '</td>';
          html += '<td><button class="strat-remove" onclick="removeCandidate(\'' + group + '\',\'' + c.symbol + '\')">移除</button></td>';
          html += '</tr>';
        });
        html += '</tbody></table>';
      }

      html += '</div>';
    });

    if (!hasContent) {
      html = '<div class="strat-empty">尚無策略資料<span>明天 08:00 自動掃描後會出現候選股</span></div>';
    }
    container.innerHTML = html;
    document.getElementById('strategy-updated').textContent = new Date().toLocaleTimeString('zh-TW', {hour:'2-digit',minute:'2-digit'});
  }).catch(function(e) {
    document.getElementById('strategy-container').innerHTML = '<div class="strat-empty" style="color:#f87171;">載入失敗: ' + e + '</div>';
  });
}

function removeCandidate(group, symbol) {
  if (!confirm('確定從 ' + group + ' 移除 ' + symbol + '？')) return;
  fetch('/api/strategy/' + group + '/candidates', {
    method: 'DELETE',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({symbol: symbol})
  }).then(r => r.json()).then(function(data) {
    if (data.ok) { showToast('✅ ' + symbol + ' 已移除', 'success'); loadStrategy(); }
    else showToast('❌ ' + (data.error || '移除失敗'), 'error');
  });
}

// 策略追蹤區塊只在 STRATEGY 功能開啟時存在
if (document.getElementById('strategy-container')) {
  loadStrategy();
  setInterval(loadStrategy, 60000);
}
