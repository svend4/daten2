// teacher-llm.js — альтернативный «учитель» на Claude (для более качественной
// разметки, если задан ANTHROPIC_API_KEY). Возвращает метку намерения из фиксированного
// набора. Дистилляция затем переносит это знание в дешёвую локальную модель.
const Anthropic = require('@anthropic-ai/sdk');
const teacher = require('./teacher');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'label_intent',
  description: 'Классифицировать намерение покупателя магазина цветов.',
  input_schema: { type: 'object', properties: { intent: { type: 'string', enum: teacher.LABELS } }, required: ['intent'] },
};

async function label(text) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 64, tools: [TOOL], tool_choice: { type: 'tool', name: 'label_intent' },
    system: `Классифицируй намерение покупателя в одну из меток: ${teacher.LABELS.join(', ')}.`,
    messages: [{ role: 'user', content: String(text || '') }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  const intent = call && call.input && call.input.intent;
  return teacher.LABELS.includes(intent) ? intent : teacher.label(text);
}

module.exports = { label, LABELS: teacher.LABELS };
