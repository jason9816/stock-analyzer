// AI 問答頁 —— 密碼保護的唯讀對話
(function () {
  'use strict';
  const log = document.getElementById('chat-log');
  const qEl = document.getElementById('chat-q');
  const pwdEl = document.getElementById('chat-pwd');
  const btn = document.getElementById('chat-send');

  function add(text, who) {
    const div = document.createElement('div');
    div.className = 'chat-msg ' + who;
    div.textContent = text;
    log.appendChild(div);
    div.scrollIntoView({ behavior: 'smooth' });
  }

  async function send() {
    const question = qEl.value.trim();
    const pwd = pwdEl.value;
    if (!question) return;
    if (!pwd) { toast('請先輸入存取密碼', 'error'); return; }
    add(question, 'me');
    qEl.value = '';
    btn.disabled = true;
    add('思考中…', 'ai');
    const thinking = log.lastChild;
    try {
      const data = await postJSON('/api/chat', { pwd: pwd, question: question });
      thinking.textContent = data.answer;
    } catch (e) {
      thinking.textContent = '✗ ' + e.message;
    } finally {
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', send);
  qEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send();
  });
})();
