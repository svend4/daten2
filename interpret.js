// interpret.js — детерминированная сводка по статусу стенда (фолбэк без ключа).
const store = require('./store');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const s = store.get();
  if (!s) return { reply: 'Статус ещё не собран — обновите портал.', engine: 'rules' };

  if (/упал|down|offline|недоступ|проблем/.test(low)) {
    const down = s.services.filter((x) => !x.up);
    if (!down.length) return { reply: `Все ${s.total} сервисов онлайн ✅`, engine: 'rules' };
    return { reply: `Offline (${down.length}):\n` + down.map((x) => `• ${x.name} (${x.id})`).join('\n'), engine: 'rules' };
  }
  if (/категор|груп|раздел/.test(low)) {
    return { reply: 'По категориям:\n' + Object.entries(s.byCat).map(([c, v]) => `• ${c}: ${v.up}/${v.total}`).join('\n'), engine: 'rules' };
  }
  if (/llm|claude|движ|engine/.test(low)) {
    const llm = s.services.filter((x) => x.engine === 'llm').length;
    return { reply: `LLM-движок активен у ${llm} сервисов, остальные — детерминированные (без ключа).`, engine: 'rules' };
  }
  return { reply: `Стенд: ${s.up}/${s.total} сервисов онлайн. ${s.down ? `Offline: ${s.down}.` : 'Всё зелёное.'}`, engine: 'rules' };
}
module.exports = { ask };
