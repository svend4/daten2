// interpret.js — детерминированные ответы о работе автономной петли (фолбэк без ключа).
const store = require('./store');
const policy = require('./policy');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const s = store.state();

  if (/одобр|очеред|pending|ждут|эскал|подтверд/.test(low)) {
    const p = store.pendingList;
    if (!p.length) return { reply: 'Очередь одобрений пуста.', engine: 'rules' };
    return { reply: `На одобрении (${p.length}):\n` + p.map((a) => `• ${a.id}: ${a.rationale} (impact ${Math.round(a.impact)})`).join('\n'), engine: 'rules' };
  }
  if (/выполн|сдела|исполн|ledger|журнал|действ/.test(low)) {
    const l = store.ledgerList.slice(-8).reverse();
    if (!l.length) return { reply: 'Действий ещё не выполнялось.', engine: 'rules' };
    return { reply: 'Последние действия:\n' + l.map((e) => `• [${e.at}${e.dryRun ? '/сухой' : ''}] ${e.action.type} ${e.action.name}: ${e.result.effect || e.result.via}`).join('\n'), engine: 'rules' };
  }
  if (/аудит|истори|audit|событ/.test(low)) {
    const a = store.auditList.slice(-10).reverse();
    return { reply: 'Аудит (последнее):\n' + a.map((e) => `• ${e.event}: ${e.type || ''} ${e.product || ''}`.trim()).join('\n'), engine: 'rules' };
  }
  if (/пауз|стоп|kill|останов|режим|сух|dry/.test(low)) {
    return { reply: `Режим: ${s.paused ? '⏸ ПАУЗА (kill-switch)' : '▶ работает'}, ${s.dryRun ? 'сухой прогон (без реальных эффектов)' : 'реальное исполнение'}. Порог авто: impact ≤ ${policy.autoThreshold}, лимит ${policy.maxActionsPerCycle}/цикл, cooldown ${policy.cooldownCycles}.`, engine: 'rules' };
  }
  return { reply: `Цикл ${s.cycle}. Снимков ${s.snapshots}, выполнено ${s.executed}, на одобрении ${s.pending}. ${s.paused ? 'На паузе.' : ''} ${s.dryRun ? 'Сухой прогон.' : 'Реальное исполнение.'}`.trim(), engine: 'rules' };
}

module.exports = { ask };
