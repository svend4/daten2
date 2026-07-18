// judge-llm.js — LLM-арбитр для эскалаций губернатора (Claude). При ANTHROPIC_API_KEY.
// По прогнозу симуляции даёт финальное суждение по действию, попавшему на эскалацию.
const Anthropic = require('@anthropic-ai/sdk');
const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'rule', description: 'Финальное решение по эскалированному действию автономного управляющего.',
  input_schema: {
    type: 'object',
    properties: {
      decision: { type: 'string', enum: ['admit', 'block', 'admit-alternative'] },
      rationale: { type: 'string' },
    },
    required: ['decision', 'rationale'],
  },
};

async function rule(evaluation) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 300, tools: [TOOL], tool_choice: { type: 'tool', name: 'rule' },
    system: 'Ты — риск-офицер магазина. Действие безопасно по жёстким стражам, но есть мягкий риск. Реши, пускать ли его в прод.',
    messages: [{ role: 'user', content: `Действие: ${JSON.stringify(evaluation.action)}. Прогноз: прибыль ${evaluation.simulated.profit} (база ${evaluation.baseline.profit}), порча ${Math.round(evaluation.simulated.spoilageRate * 100)}%, дефицит ${Math.round(evaluation.simulated.stockoutRate * 100)}%. Мягкие риски: ${evaluation.violations.filter((v) => v.severity === 'soft').map((v) => v.code).join(', ')}. Пускать?` }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  return call ? call.input : { decision: 'block', rationale: 'нет ответа' };
}
module.exports = { rule };
