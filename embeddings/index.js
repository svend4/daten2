// embeddings/index.js — выбор провайдера эмбеддингов: реальный Voyage при
// VOYAGE_API_KEY, иначе детерминированный mock. Плюс косинусная близость.
const provider = process.env.VOYAGE_API_KEY ? require('./voyage') : require('./mock');

function cosine(a, b) {
  let dot = 0, na = 0, nb = 0; const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  if (!na || !nb) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

// ранжирование документов по близости к запросу
async function rank(query, docs) {
  const vecs = await provider.embed([query, ...docs]);
  const q = vecs[0];
  return docs.map((d, i) => ({ doc: d, score: Math.round(cosine(q, vecs[i + 1]) * 1000) / 1000 }))
    .sort((a, b) => b.score - a.score);
}

module.exports = { provider, cosine, rank };
