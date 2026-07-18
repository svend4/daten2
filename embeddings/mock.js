// embeddings/mock.js — детерминированные эмбеддинги (без ключа/сети).
// Хэш-фичи (униграммы + биграммы) в фиксированную размерность, L2-нормировка.
// Один и тот же текст → один и тот же вектор; косинус осмыслен по общим токенам.
const DIM = Number(process.env.EMBED_DIM || 256);

function hash(str) { let h = 2166136261; for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
const tokenize = (s) => String(s || '').toLowerCase().split(/[^a-zа-яё0-9]+/).filter((t) => t.length >= 2);

function vector(text) {
  const v = new Float64Array(DIM);
  const toks = tokenize(text);
  for (let i = 0; i < toks.length; i++) {
    v[hash(toks[i]) % DIM] += 1;
    if (i + 1 < toks.length) v[hash(toks[i] + '_' + toks[i + 1]) % DIM] += 0.5;
  }
  let n = 0; for (let j = 0; j < DIM; j++) n += v[j] * v[j];
  n = Math.sqrt(n) || 1;
  return Array.from(v, (x) => Math.round((x / n) * 1e6) / 1e6);
}

module.exports = {
  name: 'mock', model: 'mock-hash-' + DIM, dim: DIM,
  async embed(texts) { return (texts || []).map(vector); },
};
