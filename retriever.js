// retriever.js — детерминированное извлечение чанков (RAG без внешних эмбеддингов).
// Скор по совпадению токенов запроса с тегами (вес 2) и текстом (вес 1) чанка.
const KB = require('./knowledge');

function tokens(s) {
  return String(s || '').toLowerCase().split(/[^a-zа-яё0-9]+/i).filter((t) => t.length >= 3);
}

function scoreChunk(chunk, qTokens) {
  const tagBlob = chunk.tags.join(' ').toLowerCase();
  const textBlob = chunk.text.toLowerCase();
  let score = 0;
  const hits = new Set();
  for (const t of qTokens) {
    // совпадение по корню тега (в обе стороны — «розами» ↔ «роза»)
    if (chunk.tags.some((tag) => t.startsWith(tag) || tag.startsWith(t) || tagBlob.includes(t))) { score += 2; hits.add(t); }
    else if (textBlob.includes(t)) { score += 1; hits.add(t); }
  }
  return { score, hits: [...hits] };
}

function retrieve(query, k = 3) {
  const q = tokens(query);
  const scored = KB.map((c) => ({ chunk: c, ...scoreChunk(c, q) }))
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, k);
  return scored.map((r) => ({ id: r.chunk.id, topic: r.chunk.topic, text: r.chunk.text, score: r.score, matched: r.hits }));
}

module.exports = { retrieve, tokens };
