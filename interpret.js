// interpret.js — детерминированная сводка по shadow/canary (фолбэк без ключа).
const stats = require('./stats');
const config = require('./config');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const sh = stats.shadowReport(); const cn = stats.canaryReport();

  if (/diff|различ|расхожд|shadow|тень/.test(low)) {
    if (!sh.compared) return { reply: 'Shadow-сравнений ещё не было.', engine: 'rules' };
    const r = `Shadow: сравнено ${sh.compared}, совпало ${sh.matches} (${Math.round((sh.matchRate || 0) * 100)}%), расхождений ${sh.diffs}, ошибок кандидата ${sh.candidateErrors}.`;
    const s = sh.samples[0] ? '\nПример расхождения: ' + sh.samples[0].diffs.slice(0, 2).map((d) => `${d.path} (${d.a} ≠ ${d.b})`).join(', ') : '';
    return { reply: r + s, engine: 'rules' };
  }
  if (/canary|канар|откат|rollback|процент/.test(low)) {
    return { reply: `Canary ${Math.round(config.canaryPct * 100)}%: primary ${cn.primary.served} (ошибок ${Math.round(cn.primary.errorRate * 100)}%), candidate ${cn.candidate.served} (ошибок ${Math.round(cn.candidate.errorRate * 100)}%), откатов ${cn.rollbacks}.`, engine: 'rules' };
  }
  if (/промоу|promote|повыс|готов/.test(low)) {
    const ready = sh.compared >= config.minSamples && (sh.matchRate || 0) >= 0.95 && cn.candidate.errorRate <= config.rollbackErrorRate;
    return { reply: ready ? 'Кандидат готов к промоушену: расхождений почти нет и ошибок мало.' : 'Кандидат ещё не готов: нужно больше совпадающих сравнений и низкий уровень ошибок.', engine: 'rules' };
  }
  return { reply: `Режим: ${config.mode}. Shadow совпадений ${sh.matches}/${sh.compared}. Canary ${Math.round(config.canaryPct * 100)}%, откатов ${cn.rollbacks}.`, engine: 'rules' };
}
module.exports = { ask };
