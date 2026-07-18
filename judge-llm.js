// judge-llm.js — LLM-совет по смене операционной политики (Claude). При ANTHROPIC_API_KEY.
// Интерпретирует off-policy сравнение и осторожно рекомендует: переключать/собрать
// больше данных/оставить — с учётом ненадёжности оценки (низкий ESS).
const Anthropic = require('@anthropic-ai/sdk');
const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'advise', description: 'Рекомендация по смене операционной политики на основе off-policy оценки.',
  input_schema: {
    type: 'object',
    properties: {
      action: { type: 'string', enum: ['switch', 'gather-more-data', 'keep-current'] },
      policy: { type: 'string' },
      rationale: { type: 'string' },
    },
    required: ['action', 'rationale'],
  },
};

async function advise(comparison) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 350, tools: [TOOL], tool_choice: { type: 'tool', name: 'advise' },
    system: 'Ты — осторожный аналитик AI-ops. Off-policy оценки смещены при малом ESS и слабом перекрытии носителей. Не рекомендуй переключение, если оценка ненадёжна.',
    messages: [{ role: 'user', content: `Ценность текущей политики: ${comparison.loggedValue}. Кандидаты (SNIPS, ESS, надёжность):\n${comparison.policies.map((p) => `${p.name}: V=${p.snips}, ESS=${p.ess}, confident=${p.confident}`).join('\n')}\nЧто делать?` }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  return call ? call.input : { action: 'keep-current', rationale: 'нет ответа' };
}
module.exports = { advise };
