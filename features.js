// features.js — текст → разреженный признаковый вектор (хэш-фичи: униграммы +
// биграммы токенов). Детерминированно, фиксированная размерность D.
const DIM = Number(process.env.FEATURE_DIM || 1024);

function tokenize(s) {
  return String(s || '').toLowerCase().split(/[^a-zа-яё0-9]+/).filter((t) => t.length >= 2);
}
function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0);
}

// возвращает массив { i, v } активных признаков
function featurize(text, dim = DIM) {
  const m = new Map();
  const toks = tokenize(text);
  const add = (key) => { const i = hash(key) % dim; m.set(i, (m.get(i) || 0) + 1); };
  for (let k = 0; k < toks.length; k++) {
    add(toks[k]);
    if (k + 1 < toks.length) add(toks[k] + '_' + toks[k + 1]); // биграмма
  }
  return [...m.entries()].map(([i, v]) => ({ i, v }));
}

module.exports = { featurize, tokenize, DIM };
