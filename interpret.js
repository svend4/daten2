// interpret.js — детерминированная сводка по последней верификации (фолбэк без ключа).
const store = require('./store');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const last = store.get();
  if (/codegen|клиент|генер|код/.test(low)) {
    return { reply: 'Из спецификации генерируются типизированные клиенты: JS, Python, типы TypeScript (GET /api/codegen?lang=js|python|ts-types).', engine: 'rules' };
  }
  if (!last) return { reply: 'Верификация ещё не запускалась. Проверьте провайдера против пакта (/api/verify).', engine: 'rules' };
  if (!last.ok) {
    const fails = last.results.filter((r) => !r.ok);
    return { reply: `Провайдер ${last.provider} НЕ удовлетворяет пакту (${last.passed}/${last.total}). Провалено:\n` + fails.map((f) => `• ${f.description}: ${f.statusOk ? '' : 'статус ' + f.status + '; '}${f.mismatches.map((m) => m.path + ' (ждали ' + m.expected + ', получили ' + m.got + ')').join(', ')}`).join('\n'), engine: 'rules' };
  }
  return { reply: `Провайдер ${last.provider} удовлетворяет пакту: ${last.passed}/${last.total} взаимодействий пройдено. Взаимозаменяемость подтверждена.`, engine: 'rules' };
}
module.exports = { ask };
