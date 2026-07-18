// interpret.js — детерминированная сводка по пакту поведения (фолбэк без ключа).
const store = require('./store');
const runner = require('./runner');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const last = store.getLast();
  if (!last) return { reply: 'Пакт поведения ещё не проверялся — запустите верификацию.', engine: 'rules' };

  if (/регресс|baseline|сравн|смен|модел/.test(low)) {
    const cmp = runner.compare(last, store.getBaseline());
    if (!cmp.hasBaseline) return { reply: 'Baseline не задан. Зафиксируйте текущий прогон как baseline перед сменой модели.', engine: 'rules' };
    if (!cmp.regressions.length) return { reply: `Поведенческих регрессий нет. Исправлений: ${cmp.fixes.length}. Смена модели безопасна.`, engine: 'rules' };
    return { reply: `Поведенческие регрессии (${cmp.regressions.length}):\n` + cmp.regressions.map((r) => `• ${r.name}: ${r.reason}\n  на вводе: «${r.failedInput}»`).join('\n'), engine: 'rules' };
  }
  if (!last.allHold || /наруш|провал|fail/.test(low)) {
    const fails = last.results.filter((r) => !r.ok);
    if (!fails.length) return { reply: `Все ${last.total} ожиданий держатся на ${last.agent}.`, engine: 'rules' };
    return { reply: `Нарушенные ожидания (${fails.length}):\n` + fails.map((f) => `• [${f.category}] ${f.name}: ${f.reason} (ввод «${f.failedInput}»)`).join('\n'), engine: 'rules' };
  }
  const cats = Object.entries(last.byCat).map(([c, v]) => `${c} ${v.held}/${v.total}`).join(', ');
  return { reply: `Пакт держится: ${last.held}/${last.total} ожиданий. По категориям: ${cats}.`, engine: 'rules' };
}
module.exports = { ask };
