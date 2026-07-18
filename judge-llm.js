// judge-llm.js — LLM-ревью манифеста плагина (Claude). При ANTHROPIC_API_KEY.
// Предлагает теги-возможности, оценивает риск и качество описания перед листингом.
const Anthropic = require('@anthropic-ai/sdk');
const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'review', description: 'Ревью манифеста плагина-бэкенда магазина цветов.',
  input_schema: {
    type: 'object',
    properties: {
      risk: { type: 'string', enum: ['low', 'medium', 'high'] },
      suggested_capabilities: { type: 'array', items: { type: 'string' } },
      note: { type: 'string' },
    },
    required: ['risk'],
  },
};

async function review(manifest) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 300, tools: [TOOL], tool_choice: { type: 'tool', name: 'review' },
    system: 'Ты — куратор маркетплейса бэкендов. Оцени риск и предложи теги-возможности по манифесту.',
    messages: [{ role: 'user', content: `Манифест: ${JSON.stringify(manifest)}. Ревью?` }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  return call ? call.input : { risk: 'low' };
}
module.exports = { review };
