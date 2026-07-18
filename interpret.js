// interpret.js — детерминированная сводка по chaos-прогону (фолбэк без ключа).
const store = require('./store');
const targetsMod = require('./targets');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  if (/цел|уров|fault|сбой|состоян/.test(low)) {
    return { reply: 'Уровни:\n' + targetsMod.targets.map((t) => `• ${t.name}: ${t.fault.down ? 'DOWN' : `latency ${t.fault.latencyMs}мс, errors ${Math.round(t.fault.errorRate * 100)}%`}`).join('\n'), engine: 'rules' };
  }
  const last = store.get();
  if (!last) return { reply: 'Chaos-прогон ещё не запускался.', engine: 'rules' };
  if (/провал|fail|не прош|нарушен/.test(low)) {
    const fails = last.results.filter((r) => !r.pass);
    if (!fails.length) return { reply: `Все ${last.total} экспериментов прошли: система устойчива, failover держит SLO.`, engine: 'rules' };
    return { reply: `Не прошли (${fails.length}):\n` + fails.map((f) => `• ${f.name}: SLO ${f.held ? 'держался' : 'нарушен'} (ожидалось ${f.expectSlo ? 'держится' : 'ломается'})`).join('\n'), engine: 'rules' };
  }
  return { reply: `Chaos-прогон: ${last.passed}/${last.total} как ожидалось. ${last.allPass ? 'Устойчивость подтверждена.' : 'Есть отклонения — failover не держит SLO.'}`, engine: 'rules' };
}
module.exports = { ask };
