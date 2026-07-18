// judge-llm.js — LLM-объяснение расхождения портов (Claude). Активен при ANTHROPIC_API_KEY.
// Классифицирует расхождение: баг реализации / допустимая вариация / расхождение данных.
const Anthropic = require('@anthropic-ai/sdk');
const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'classify', description: 'Классифицировать расхождение между языковыми портами одного контракта.',
  input_schema: {
    type: 'object',
    properties: {
      kind: { type: 'string', enum: ['implementation-bug', 'data-drift', 'acceptable-variation'] },
      severity: { type: 'string', enum: ['low', 'medium', 'high'] },
      explanation: { type: 'string' },
    },
    required: ['kind', 'severity'],
  },
};

async function classify(divergence) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 300, tools: [TOOL], tool_choice: { type: 'tool', name: 'classify' },
    system: 'Ты — аудитор совместимости языковых портов одного REST-контракта магазина цветов. Реализации ОБЯЗАНЫ вести себя одинаково на наблюдаемых полях.',
    messages: [{ role: 'user', content: `Расхождение порта «${divergence.backend}» на шаге «${divergence.step}», путь «${divergence.path}»: эталон ${JSON.stringify(divergence.reference)}, порт ${JSON.stringify(divergence.actual)}. Это баг реализации, дрейф данных или допустимая вариация?` }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  return call ? call.input : { kind: 'implementation-bug', severity: 'medium' };
}
module.exports = { classify };
