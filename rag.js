// rag.js — сборка ответа: извлечение из базы знаний + пер-клиентская память.
// Детерминированный построитель (фолбэк без ключа) и персонализированные рекомендации.
const retriever = require('./retriever');
const memory = require('./memory');

// повод → корень названия товара (для персонализации)
const OCCASION_ROOT = { 'романтик': 'роз', 'свидание': 'роз', 'любовь': 'роз', 'маме': 'пион', 'мама': 'пион', 'день рождения': 'тюльпан', 'юбилей': 'тюльпан' };
const nameRoot = (name) => String(name || '').toLowerCase();

function answer(customerId, question) {
  const sources = retriever.retrieve(question, 3);
  const mem = memory.recall(customerId);
  memory.remember(customerId, { event: { t: 'question', q: String(question).slice(0, 120) } });

  if (!sources.length) {
    return { answer: 'Не нашёл это в базе знаний магазина. Уточните вопрос — про уход, повод, доставку, оплату или замену.', sources: [], usedMemory: mem.preferences, engine: 'rules' };
  }
  let ans = sources[0].text;
  // персонализация по памяти
  const fav = (mem.preferences.favorites || [])[0];
  if (fav && sources.length) ans += `\nКстати, вы любите «${fav}» — подскажу подходящий букет, если нужно.`;
  return { answer: ans, sources: sources.map((s) => ({ id: s.id, topic: s.topic, score: s.score })), usedMemory: mem.preferences, engine: 'rules' };
}

function recommend(customerId, catalog) {
  const mem = memory.recall(customerId);
  const pref = mem.preferences;
  const favRoots = (pref.favorites || []).map(nameRoot);
  const occRoots = (pref.occasions || []).map((o) => OCCASION_ROOT[String(o).toLowerCase()]).filter(Boolean);

  const scored = catalog.map((p) => {
    const n = nameRoot(p.name);
    let score = p.is_featured ? 0.5 : 0.1;
    const reasons = [];
    if (favRoots.some((f) => f && n.includes(f))) { score += 1.0; reasons.push('любимый'); }
    if (occRoots.some((r) => n.includes(r))) { score += 0.6; reasons.push('под повод'); }
    if (pref.budget != null && Number(p.price) <= pref.budget) { score += 0.3; reasons.push('в бюджете'); }
    return { id: p.id, name: p.name, price: Number(p.price), score: Math.round(score * 100) / 100, reasons };
  });
  const filtered = pref.budget != null ? scored.filter((x) => x.price <= pref.budget || x.reasons.includes('любимый')) : scored;
  return { customerId, preferences: pref, recommendations: filtered.sort((a, b) => b.score - a.score).slice(0, 5) };
}

module.exports = { answer, recommend };
