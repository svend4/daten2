// embeddings/voyage.js — реальные эмбеддинги через Voyage AI (Anthropic не даёт
// embeddings-API). Активен при VOYAGE_API_KEY. Тот же интерфейс: embed(texts) → vectors.
const KEY = process.env.VOYAGE_API_KEY || '';
const MODEL = process.env.VOYAGE_MODEL || 'voyage-3';

module.exports = {
  name: 'voyage', model: MODEL, dim: null,
  async embed(texts) {
    const r = await fetch('https://api.voyageai.com/v1/embeddings', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + KEY, 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: texts || [], model: MODEL }),
    });
    const body = await r.json();
    if (!r.ok) throw new Error(body && body.detail ? body.detail : 'Voyage HTTP ' + r.status);
    return (body.data || []).sort((a, b) => a.index - b.index).map((d) => d.embedding);
  },
};
