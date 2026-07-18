// effectors.js — исполнители действий. Единый контракт намеренно read-mostly
// (нет ops-записи), поэтому по умолчанию эффектор — безопасный ledger (фиксирует
// и симулирует эффект). В реальном развёртывании EFFECTOR_URL направляет действия
// на реальную систему (поставщик, админ-API уровня) через вебхук.
const EFFECTOR_URL = (process.env.EFFECTOR_URL || '').replace(/\/$/, '');

async function execute(action, { dryRun }) {
  if (dryRun) return { ok: true, via: 'dry-run', effect: 'симулировано (без реального эффекта)' };
  if (EFFECTOR_URL) {
    try {
      const r = await fetch(EFFECTOR_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(action), signal: AbortSignal.timeout(4000) });
      return { ok: r.ok, via: 'webhook', status: r.status };
    } catch (e) { return { ok: false, via: 'webhook', error: String(e.message) }; }
  }
  // ledger-эффектор: действие зафиксировано как выполненное
  return { ok: true, via: 'ledger', effect: describe(action) };
}

function describe(a) {
  if (a.type === 'reorder') return `дозаказ ${a.name}: +${a.params.quantity} на ${a.params.cost} €`;
  if (a.type === 'price_change') return `цена ${a.name}: ${a.params.from}→${a.params.to} €`;
  if (a.type === 'flag') return `помечена аномалия ${a.name}: ${(a.params.anomalies || []).map((x) => x.type).join(', ')}`;
  return `действие ${a.type} для ${a.name}`;
}

module.exports = { execute, describe };
