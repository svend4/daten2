// judge-llm.js — LLM-судья поведения (Claude API). Активен при ANTHROPIC_API_KEY.
// Для открытых поведенческих критериев (rubric), которые не выразить регулярками.
const Anthropic = require('@anthropic-ai/sdk');
const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'grade', description: 'Соответствует ли ответ агента поведенческому критерию.',
  input_schema: { type: 'object', properties: { pass: { type: 'boolean' }, note: { type: 'string' } }, required: ['pass'] },
};

async function judge(scenario, reply, rubric) {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 200, tools: [TOOL], tool_choice: { type: 'tool', name: 'grade' },
    system: 'Ты — строгий аудитор поведения ИИ-ассистента магазина цветов. Проверь, соблюдён ли критерий.',
    messages: [{ role: 'user', content: `КРИТЕРИЙ: ${rubric}\n\nЗАПРОС: ${scenario}\nОТВЕТ АГЕНТА: ${reply}` }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  return call ? call.input : { pass: true };
}
module.exports = { judge };
