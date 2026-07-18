// judge-llm.js — LLM-совет по углеродной стратегии (Claude). При ANTHROPIC_API_KEY.
// Интерпретирует план и предлагает политику: агрессивнее сдвигать / ослабить
// дедлайны / докупить зелёную ёмкость в конкретном регионе.
const Anthropic = require('@anthropic-ai/sdk');
const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'advise', description: 'Рекомендация по стратегии углеродного арбитража нагрузок.',
  input_schema: {
    type: 'object',
    properties: {
      strategy: { type: 'string', enum: ['shift-more-aggressively', 'relax-deadlines', 'add-green-capacity', 'already-optimal'] },
      region: { type: 'string' },
      rationale: { type: 'string' },
    },
    required: ['strategy', 'rationale'],
  },
};

async function advise(plan) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 300, tools: [TOOL], tool_choice: { type: 'tool', name: 'advise' },
    system: 'Ты — аналитик carbon-aware вычислений. Советуй, как увеличить выигрыш CO2 без нарушения дедлайнов и резидентности данных.',
    messages: [{ role: 'user', content: `План: сдвинуто ${plan.shifted}/${plan.jobs}, экономия CO2 ${plan.savings.carbonPct}% (${plan.savings.carbon} г), денег ${plan.savings.costPct}%. Что улучшить?` }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  return call ? call.input : { strategy: 'already-optimal', rationale: 'нет ответа' };
}
module.exports = { advise };
