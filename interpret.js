// interpret.js — детерминированная сводка по кросс-языковой эквивалентности.
const store = require('./store');
const runner = require('./runner');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const last = store.getLast();
  if (!last) return { reply: 'Портов ещё не сверял — запустите верификацию.', engine: 'rules' };

  if (/baseline|регресс|нов|принят|waiver/.test(low)) {
    const cmp = runner.compare(last, store.getBaseline());
    if (!cmp.hasBaseline) return { reply: 'Baseline не задан. Зафиксируйте текущие расхождения как принятые (waiver), тогда новые будут видны отдельно.', engine: 'rules' };
    if (!cmp.newDivergences.length) return { reply: `Новых расхождений против baseline нет (устранено: ${cmp.resolved.length}).`, engine: 'rules' };
    return { reply: `Новые расхождения (${cmp.newDivergences.length}):\n` + cmp.newDivergences.map((d) => `• ${d.backend} · ${d.step} · ${d.path}: эталон ${JSON.stringify(d.reference)} ≠ ${JSON.stringify(d.actual)}`).join('\n'), engine: 'rules' };
  }
  if (last.allEquivalent) {
    return { reply: `Все ${last.backends.length} портов эквивалентны эталону «${last.reference}» на ${last.steps.length} шагах контракта.`, engine: 'rules' };
  }
  const bad = Object.entries(last.byBackend).filter(([n, v]) => n !== last.reference && (!v.ok || v.divergent)).map(([n]) => n);
  const lines = last.divergences.slice(0, 12).map((d) => `• ${d.backend} · ${d.step} · ${d.path}: эталон ${JSON.stringify(d.reference)} ≠ ${JSON.stringify(d.actual)}`);
  return { reply: `Эталон «${last.reference}». Расходятся: ${bad.join(', ') || '—'} (всего расхождений ${last.divergences.length}).\n` + lines.join('\n'), engine: 'rules' };
}
module.exports = { ask };
