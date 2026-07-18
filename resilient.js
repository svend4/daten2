// resilient.js — устойчивый фронт (SUT): failover по пулу уровней.
// Пробует уровни по порядку; при сбое переходит к следующему. Именно его SLO
// проверяет chaos-харнесс: держится ли доступность, когда уровни падают/тормозят.
const chaos = require('./chaos');

async function request(targets, { method = 'GET', path = '/api/products', body } = {}) {
  const start = Date.now();
  let attempt = 0;
  for (const t of targets) {
    const r = await chaos.forward(t, method, path, body);
    if (r.ok) return { ok: true, status: r.status, body: r.body, servedBy: t.id, failover: attempt > 0, ms: Date.now() - start };
    attempt++;
  }
  return { ok: false, status: 503, servedBy: null, failover: attempt > 1, ms: Date.now() - start };
}

module.exports = { request };
