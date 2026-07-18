// advisor.js — LLM-объяснение решений green/FinOps-роутера (Claude, цикл tool-use).
// Активен при ANTHROPIC_API_KEY. Данные — только из инструмента router_state.
const Anthropic = require('@anthropic-ai/sdk');
const model = require('./model');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const SYSTEM = `Ты — FinOps/эко-аналитик роутера магазина цветов. Роутер выбирает уровень
по композитной стоимости: латентность, деньги (€/запрос), углерод (CO2/запрос),
надёжность — со взвешиванием. Объясняй выбор и подсказывай, как сместить веса ради
скорости/экономии/экологии. Данные — только из router_state. Кратко, по-русски.`;

const TOOLS = [{ name: 'router_state', description: 'Решение (composite, latency, cost, co2 по уровням), веса и FinOps-итоги.', input_schema: { type: 'object', properties: {} } }];

async function ask(session, text) {
  session.messages = session.messages || [];
  session.messages.push({ role: 'user', content: text });
  let guard = 0;
  while (guard++ < 6) {
    const resp = await client.messages.create({ model: MODEL, max_tokens: 800, system: SYSTEM, tools: TOOLS, messages: session.messages });
    session.messages.push({ role: 'assistant', content: resp.content });
    if (resp.stop_reason !== 'tool_use') return { reply: resp.content.filter((b) => b.type === 'text').map((b) => b.text).join('\n') || '(нет ответа)', engine: 'llm' };
    const results = [];
    for (const block of resp.content) if (block.type === 'tool_use') results.push({ type: 'tool_result', tool_use_id: block.id, content: JSON.stringify({ decision: model.decide(), finops: model.finops() }) });
    session.messages.push({ role: 'user', content: results });
  }
  return { reply: 'Не удалось объяснить решение.', engine: 'llm' };
}
module.exports = { ask };
