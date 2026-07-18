// judge-llm.js — LLM-разбор регрессии качества модели (Claude). При ANTHROPIC_API_KEY.
// По просевшим примерам предполагает причину дрейфа и рекомендует действие.
const Anthropic = require('@anthropic-ai/sdk');
const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'diagnose', description: 'Диагноз просадки согласия распознавателя намерений с учителем.',
  input_schema: {
    type: 'object',
    properties: {
      cause: { type: 'string', enum: ['concept-drift', 'canary-blindspot', 'undertrained', 'data-shift'] },
      action: { type: 'string', enum: ['keep-rollback', 'retrain', 'expand-eval-set'] },
      note: { type: 'string' },
    },
    required: ['cause', 'action'],
  },
};

async function diagnose(examples) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 300, tools: [TOOL], tool_choice: { type: 'tool', name: 'diagnose' },
    system: 'Ты — MLOps-инженер. По расхождениям модель↔учитель определи причину и действие.',
    messages: [{ role: 'user', content: `Расхождения (реплика → предсказано vs верно):\n${examples.slice(0, 20).map((e) => `«${e.text}» → ${e.pred} vs ${e.truth}`).join('\n')}` }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  return call ? call.input : { cause: 'concept-drift', action: 'keep-rollback' };
}
module.exports = { diagnose };
