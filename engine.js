// engine.js — замкнутая петля: наблюдение → анализ → предложение → шлюз (авто /
// эскалация человеку) → исполнение → аудит. Предохранители: kill-switch, лимит
// действий за цикл, cooldown по товару, сухой прогон.
const analytics = require('./analytics');
const actions = require('./actions');
const effectors = require('./effectors');
const store = require('./store');
const policy = require('./policy');

async function apply(action, reason) {
  const res = await effectors.execute(action, { dryRun: policy.dryRun });
  const entry = { at: reason, action, result: res, dryRun: policy.dryRun, ts: store.currentCycle() };
  store.addLedger(entry);
  store.setCooldown(action.productId);
  store.audited({ event: policy.dryRun ? 'simulated' : 'executed', reason, id: action.id, type: action.type, product: action.name, impact: action.impact, via: res.via });
  return entry;
}

// один цикл управления
async function cycle() {
  if (store.isPaused()) return { paused: true, note: 'петля на паузе (kill-switch)' };
  const n = store.nextCycle();
  const report = analytics.report(store.allSnapshots());
  if (!report.generatedFrom) return { cycle: n, note: 'нет данных: сначала соберите снимки', proposed: 0 };

  const proposed = actions.propose(report, n);
  const summary = { cycle: n, proposed: proposed.length, auto_executed: 0, queued: 0, skipped: [], details: [] };
  let autoCount = 0;

  for (const a of proposed) {
    store.audited({ event: 'proposed', id: a.id, type: a.type, product: a.name, impact: a.impact });
    if (store.onCooldown(a.productId)) { summary.skipped.push({ id: a.id, reason: 'cooldown' }); summary.details.push({ id: a.id, decision: 'skipped-cooldown' }); continue; }

    if (a.impact > policy.autoThreshold) {
      // выше порога — только с одобрения человека
      store.addPending(a);
      store.audited({ event: 'queued', id: a.id, type: a.type, product: a.name, impact: a.impact });
      summary.queued++; summary.details.push({ id: a.id, decision: 'queued-for-approval', impact: a.impact });
      continue;
    }
    // авто, но не больше лимита за цикл
    if (autoCount >= policy.maxActionsPerCycle) { summary.skipped.push({ id: a.id, reason: 'rate-limit' }); summary.details.push({ id: a.id, decision: 'skipped-rate-limit' }); continue; }
    await apply(a, 'auto');
    autoCount++; summary.auto_executed++; summary.details.push({ id: a.id, decision: policy.dryRun ? 'auto-simulated' : 'auto-executed' });
  }
  return summary;
}

// решение человека по эскалированному действию
async function approve(id) {
  const a = store.takePending(id);
  if (!a) return { ok: false, error: 'действие не найдено в очереди' };
  const entry = await apply(a, 'approved');
  store.audited({ event: 'approved', id, type: a.type, product: a.name });
  return { ok: true, executed: entry };
}
function reject(id, note) {
  const a = store.takePending(id);
  if (!a) return { ok: false, error: 'действие не найдено в очереди' };
  store.audited({ event: 'rejected', id, type: a.type, product: a.name, note: note || '' });
  return { ok: true, rejected: a };
}

module.exports = { cycle, approve, reject };
