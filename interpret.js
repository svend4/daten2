// interpret.js — детерминированная сводка по scorecard (фолбэк без ключа).
const scorecard = require('./scorecard');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const last = scorecard.getLast();
  if (!last) return { reply: 'Эвалы ещё не запускались — нажмите «Прогнать».', engine: 'rules' };

  if (/регресс|сравн|baseline|базов|ухудш/.test(low)) {
    const cmp = scorecard.compare(last, scorecard.getBaseline());
    if (!cmp.hasBaseline) return { reply: 'Baseline не задан. Сохраните текущий прогон как baseline для контроля регрессий.', engine: 'rules' };
    if (!cmp.regressions.length) return { reply: `Регрессий нет. Δбалл ${cmp.scoreDelta >= 0 ? '+' : ''}${cmp.scoreDelta}. Исправлений: ${cmp.fixes.length}.`, engine: 'rules' };
    return { reply: `Регрессии (${cmp.regressions.length}):\n` + cmp.regressions.map((r) => `• ${r.name}: ${r.detail}`).join('\n'), engine: 'rules' };
  }
  if (/провал|упал|fail|не прош|ошибк/.test(low)) {
    const fails = last.results.filter((r) => !r.pass);
    if (!fails.length) return { reply: `Все ${last.total} кейсов пройдены (балл ${last.score}).`, engine: 'rules' };
    return { reply: `Провалено (${fails.length}/${last.total}):\n` + fails.map((r) => `• ${r.name}: ${r.detail}`).join('\n'), engine: 'rules' };
  }
  return { reply: `Последний прогон (${last.suite}) по ${last.target}: балл ${last.score}, пройдено ${last.passed}/${last.total}.`, engine: 'rules' };
}
module.exports = { ask };
