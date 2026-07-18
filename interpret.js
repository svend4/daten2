// interpret.js — детерминированная сводка по охоте на уязвимости.
const store = require('./store');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const last = store.getLast();
  if (!last) return { reply: 'Охота ещё не запускалась — запустите поиск атак против агента.', engine: 'rules' };

  if (/устойч|robust|надёжн|защищ/.test(low)) {
    return { reply: `Устойчивость агента: ${last.robustness} (сломано ${last.distinctBroken} из ${last.totalTactics} классов атак за ${last.generations} поколений).`, engine: 'rules' };
  }
  if (!last.attackSurface.length) return { reply: `Эволюционный поиск не нашёл пробоев за ${last.generations} поколений — агент устойчив (${last.robustness}).`, engine: 'rules' };
  const lines = last.exploits.map((e) => `• [${e.category}] ${e.tactic}: ${e.evidence}\n  атака (интенсивность ${Math.round(e.intensity * 100) / 100}): «${e.message}»\n  ответ: «${e.reply}»`);
  return { reply: `Найдено ${last.attackSurface.length} класса пробоев (устойчивость ${last.robustness}):\n` + lines.join('\n'), engine: 'rules' };
}
module.exports = { ask };
