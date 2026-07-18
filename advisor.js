// advisor.js — LLM-аналитик событийного потока (Claude API). Активен при ANTHROPIC_API_KEY.
// Отвечает на вопросы по проекциям (свёртке событий), переданным в контексте.
const Anthropic = require('@anthropic-ai/sdk');
const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const SYSTEM = `Ты — аналитик магазина цветов поверх событийной шины. Тебе дают
проекции (свёртку доменных событий): заказы, выручка, изменения цен и остатков,
счётчики по типам. Отвечай по этим данным, кратко, по-деловому, по-русски.`;

async function ask(session, text, state) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 700, system: SYSTEM,
    messages: [{ role: 'user', content: `ПРОЕКЦИИ:\n${JSON.stringify(state)}\n\nВОПРОС: ${text}` }],
  });
  return { reply: resp.content.filter((b) => b.type === 'text').map((b) => b.text).join('\n') || '(нет ответа)', engine: 'llm' };
}
module.exports = { ask };
