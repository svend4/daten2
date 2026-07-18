// advisor.js — LLM-объяснение решений роутера (Claude API, цикл tool-use).
// Активен при ANTHROPIC_API_KEY. Оператор спрашивает на естественном языке; Claude
// берёт живую статистику ТОЛЬКО из инструмента router_stats и объясняет выбор.
const Anthropic = require('@anthropic-ai/sdk');
const brain = require('./brain');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const SYSTEM = `Ты — SRE-помощник самооптимизирующегося роутера магазина цветов.
Роутер выбирает уровень (бэкенд) по онлайн-модели: латентность, надёжность,
стоимость, нагрузка; выбор — UCB (эксплуатация + разведка). Объясняй решения,
опираясь ТОЛЬКО на данные router_stats (utility, latencyEwma, success, cost, n).
Отвечай кратко, по-деловому, по-русски.`;

const TOOLS = [{
  name: 'router_stats',
  description: 'Живое состояние роутера: текущий выбор и метрики по каждому уровню (utility, latencyEwma, success, cost, inflight, n, alive).',
  input_schema: { type: 'object', properties: {} },
}];

async function ask(session, text) {
  session.messages = session.messages || [];
  session.messages.push({ role: 'user', content: text });
  let guard = 0;
  while (guard++ < 6) {
    const resp = await client.messages.create({ model: MODEL, max_tokens: 900, system: SYSTEM, tools: TOOLS, messages: session.messages });
    session.messages.push({ role: 'assistant', content: resp.content });
    if (resp.stop_reason !== 'tool_use') {
      const out = resp.content.filter((b) => b.type === 'text').map((b) => b.text).join('\n');
      return { reply: out || '(нет ответа)', engine: 'llm' };
    }
    const results = [];
    for (const block of resp.content) {
      if (block.type === 'tool_use') {
        const data = { decision: brain.decide(), levels: brain.snapshot() };
        results.push({ type: 'tool_result', tool_use_id: block.id, content: JSON.stringify(data) });
      }
    }
    session.messages.push({ role: 'user', content: results });
  }
  return { reply: 'Не удалось объяснить решение.', engine: 'llm' };
}

module.exports = { ask };
