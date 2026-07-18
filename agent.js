// agent.js — клиент к тестируемому агенту (chat-контракт: POST {sessionId, message} → {reply}).
function client(base, path) {
  const url = String(base || '').replace(/\/$/, '');
  const p = path || process.env.AGENT_PATH || '/api/chat';
  let seq = 0;
  return {
    url: url + p,
    async send(message) {
      const r = await fetch(url + p, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId: 'pact-' + (++seq), message }),
        signal: AbortSignal.timeout(Number(process.env.PACT_TIMEOUT_MS || 8000)),
      });
      let b; try { b = await r.json(); } catch { b = {}; }
      return (b && (b.reply || b.answer || b.text || b.message)) || '';
    },
  };
}
module.exports = { client };
