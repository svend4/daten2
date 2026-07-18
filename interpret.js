// interpret.js — детерминированная сводка по журналу решений и контрфактам.
const ope = require('./ope');

function ask(ledger, text) {
  const low = (text || '').toLowerCase();
  const decisions = ledger.state();
  const resolved = decisions.filter((d) => d.reward != null);
  if (!decisions.length) return { reply: 'Журнал решений пуст — залогируйте решения и их исходы.', engine: 'rules' };

  if (/целостн|tamper|цепь|подмен|integrity|hash|хэш/.test(low)) {
    const v = ledger.verify();
    return { reply: v.ok ? `Хэш-цепь цела: ${v.length} событий, журнал доказуемо append-only.` : `⚠ Цепь нарушена на событии #${v.brokenAt} — журнал подделан после записи.`, engine: 'rules' };
  }
  if (!resolved.length) return { reply: `Решений залогировано: ${decisions.length}, но исходов пока нет — контрфактуальная оценка появится после resolve.`, engine: 'rules' };

  const cmp = ope.comparePolicies(resolved);
  if (/политик|policy|лучш|перекл|regret|сожал|контрфакт|что было бы|counterfactual/.test(low)) {
    const top = cmp.policies.slice(0, 5).map((p) => `• ${p.name}: V≈${p.snips} (ESS ${p.ess}${p.confident ? '' : ', ненадёжно'})`).join('\n');
    return { reply: `Ценность логирующей политики: ${cmp.loggedValue}. Оценки off-policy (SNIPS):\n${top}\n${cmp.recommendation}`, engine: 'rules' };
  }
  return { reply: `В журнале ${decisions.length} решений (${resolved.length} с исходом) по доменам: ${ledger.domains().join(', ')}. Лучшая из рассмотренных политик — «${cmp.best}» (regret ${cmp.regret}).`, engine: 'rules' };
}
module.exports = { ask };
