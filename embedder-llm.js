// embedder-llm.js — LLM-энкодер запроса (Claude API).
// Активен при ANTHROPIC_API_KEY. Claude оценивает произвольный запрос по тем же
// смысловым осям, что и детерминированный энкодер, — точнее ловит перефразировки
// и синонимы. Anthropic не даёт embeddings-API, поэтому семантику извлекает модель
// в общее интерпретируемое пространство осей (structured output через инструмент).
const Anthropic = require('@anthropic-ai/sdk');
const enc = require('./encoder');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const props = Object.fromEntries(enc.AXES.map((a) => [a.key, {
  type: 'number', minimum: 0, maximum: 1, description: `Насколько запрос про «${a.label}» (0..1)`,
}]));

const TOOL = {
  name: 'rate_axes',
  description: 'Оценить, насколько запрос покупателя относится к каждой смысловой оси букета (0..1).',
  input_schema: { type: 'object', properties: props, required: enc.KEYS },
};

const SYSTEM = `Ты кодируешь запрос покупателя цветов в вектор смысловых осей.
Верни оценку 0..1 по каждой оси через инструмент rate_axes. Оценивай ТОЛЬКО то,
что явно или по смыслу есть в запросе; неупомянутое — близко к 0.`;

async function encodeText(text) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 512, system: SYSTEM, tools: [TOOL],
    tool_choice: { type: 'tool', name: 'rate_axes' },
    messages: [{ role: 'user', content: String(text || '') }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  const out = enc.encodeText(''); // нулевой вектор нужной формы
  if (call && call.input) for (const k of enc.KEYS) {
    const v = Number(call.input[k]);
    if (!Number.isNaN(v)) out[k] = Math.max(0, Math.min(1, v));
  }
  return out;
}

module.exports = { encodeText };
