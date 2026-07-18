// judge-llm.js — LLM-арбитр спора по расчёту (Claude). При ANTHROPIC_API_KEY.
// По описанию спора рекомендует: держать расчёт / реверсировать / частичный возврат.
const Anthropic = require('@anthropic-ai/sdk');
const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'adjudicate', description: 'Разрешить спор по расчёту между агентами.',
  input_schema: {
    type: 'object',
    properties: {
      decision: { type: 'string', enum: ['uphold', 'reverse', 'partial-refund'] },
      rationale: { type: 'string' },
    },
    required: ['decision', 'rationale'],
  },
};

async function adjudicate(settlement, complaint) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 300, tools: [TOOL], tool_choice: { type: 'tool', name: 'adjudicate' },
    system: 'Ты — нейтральный арбитр расчётов агент-агенту в магазине цветов. Реверс уместен при неисполнении обязательства; при исполнении — держать расчёт.',
    messages: [{ role: 'user', content: `Расчёт: ${JSON.stringify(settlement.legs)} (состояние ${settlement.state}). Жалоба: ${complaint}. Что решить?` }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  return call ? call.input : { decision: 'uphold', rationale: 'нет ответа' };
}
module.exports = { adjudicate };
