// explain.js — детерминированное объяснение решений роутера (фолбэк без LLM-ключа).
const brain = require('./brain');

const ms = (n) => (n == null ? 'нет данных' : Math.round(n) + ' мс');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const { choice, scored } = brain.decide();
  if (!scored.length) return { reply: 'Пул пуст — нет бэкендов.', engine: 'rules' };

  // сравнение / таблица
  if (/сравн|таблиц|все|список|стат/.test(low)) {
    const lines = scored.map((s) => `• ${s.name}: полезность ${s.utility}, латентность ${ms(s.latencyEwma)}, надёжность ${Math.round(s.success * 100)}%, стоимость ×${s.cost}, проб ${s.n}${s.alive ? '' : ' (offline)'}`);
    return { reply: 'Текущее состояние уровней:\n' + lines.join('\n'), engine: 'rules' };
  }
  // надёжность / аномалии
  if (/надёжн|надежн|ошибк|сбой|падает|offline|недоступ/.test(low)) {
    const weak = scored.filter((s) => s.success < 0.8 || !s.alive);
    if (!weak.length) return { reply: 'Все уровни здоровы: надёжность ≥ 80%.', engine: 'rules' };
    return { reply: 'Проблемные уровни:\n' + weak.map((s) => `• ${s.name}: надёжность ${Math.round(s.success * 100)}%${s.alive ? '' : ', offline'}`).join('\n'), engine: 'rules' };
  }
  // почему выбран
  const top = scored[0];
  const why = [];
  why.push(`Сейчас роутер выбирает «${top.name}».`);
  why.push(`Полезность ${top.utility} (латентность ${ms(top.latencyEwma)}, надёжность ${Math.round(top.success * 100)}%, стоимость ×${top.cost}).`);
  const rival = scored[1];
  if (rival) why.push(`Ближайший — «${rival.name}» с полезностью ${rival.utility}. Разрыв ${Math.round((top.score - rival.score) * 1000) / 1000}.`);
  why.push('Иногда роутер пробует другие уровни (разведка UCB), чтобы замечать изменения нагрузки и стоимости.');
  return { reply: why.join(' '), engine: 'rules', choice };
}

module.exports = { ask };
