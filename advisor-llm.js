// advisor-llm.js — grounded-ответ на Claude (RAG). Активен при ANTHROPIC_API_KEY.
// Claude отвечает СТРОГО по извлечённым чанкам + памяти клиента; не выдумывает.
const Anthropic = require('@anthropic-ai/sdk');
const retriever = require('./retriever');
const memory = require('./memory');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const SYSTEM = `Ты — консультант магазина цветов. Отвечай ТОЛЬКО на основе
предоставленных фрагментов базы знаний (CONTEXT) и памяти клиента (MEMORY).
Если ответа нет в контексте — так и скажи, не выдумывай. Персонализируй под память
клиента. Кратко, дружелюбно, по-русски.`;

async function answer(customerId, question) {
  const sources = retriever.retrieve(question, 3);
  const mem = memory.recall(customerId);
  memory.remember(customerId, { event: { t: 'question', q: String(question).slice(0, 120) } });

  const context = sources.map((s) => `[${s.topic}] ${s.text}`).join('\n');
  const memBlob = JSON.stringify(mem.preferences);
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 600, system: SYSTEM,
    messages: [{ role: 'user', content: `CONTEXT:\n${context || '(пусто)'}\n\nMEMORY:\n${memBlob}\n\nВОПРОС: ${question}` }],
  });
  const text = resp.content.filter((b) => b.type === 'text').map((b) => b.text).join('\n');
  return { answer: text || '(нет ответа)', sources: sources.map((s) => ({ id: s.id, topic: s.topic, score: s.score })), usedMemory: mem.preferences, engine: 'llm' };
}

module.exports = { answer };
