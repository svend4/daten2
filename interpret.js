// interpret.js — детерминированная сводка по решениям губернатора.
const store = require('./store');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const log = store.log();
  if (!log.length) return { reply: 'Губернатор ещё не рассматривал действий.', engine: 'rules' };
  const last = log[log.length - 1];

  if (/блок|заблок|отклон|почему|block|небезопас/.test(low)) {
    const blocked = log.filter((e) => e.decision === 'block');
    if (!blocked.length) return { reply: 'Заблокированных действий нет.', engine: 'rules' };
    const b = blocked[blocked.length - 1];
    return { reply: `Последний блок: ${b.reason}. Нарушения: ${(b.violations || []).map((v) => v.code).join(', ') || '—'}.${b.recommendation ? ' Рекомендована безопасная альтернатива: ' + JSON.stringify(b.recommendation.action) : ''}`, engine: 'rules' };
  }
  if (/последн|last|решени/.test(low)) {
    return { reply: `Последнее: ${last.decision} — ${last.reason}. Прогноз прибыли ${last.simulated.profit} (база ${last.baseline.profit}, uplift ${last.uplift}).`, engine: 'rules' };
  }
  const st = store.stats();
  return { reply: `Рассмотрено ${st.total} действий: допущено ${st.admit || 0}, эскалировано ${st.escalate || 0}, заблокировано ${st.block || 0}. Каждое сперва проверено на двойнике.`, engine: 'rules' };
}
module.exports = { ask };
