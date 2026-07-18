// advisor.js — LLM-аналитик прогонов двойника (Claude API, цикл tool-use).
// Активен при ANTHROPIC_API_KEY. Цифры — ТОЛЬКО из инструмента twin_results.
const Anthropic = require('@anthropic-ai/sdk');
const store = require('./store');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const SYSTEM = `Ты — аналитик цифрового двойника магазина цветов. Есть прогон
симуляции: посетители, конверсия, выручка, средний чек, продажи по товарам и
сегментам, при желании what-if по цене. Отвечай на вопросы владельца, опираясь
ТОЛЬКО на twin_results; давай выводы и рекомендации с числами. Кратко, по-русски.`;

const TOOLS = [{
  name: 'twin_results',
  description: 'Итоги последнего прогона: totals (arrivals, purchases, conversion_rate, revenue, aov), unitsByProduct, bySegment, whatif (если был), mode.',
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
        const run = store.get();
        const data = run ? { mode: run.mode, totals: run.totals, unitsByProduct: run.unitsByProduct, bySegment: run.bySegment, whatif: run.whatif || null } : { error: 'симуляция ещё не запускалась' };
        results.push({ type: 'tool_result', tool_use_id: block.id, content: JSON.stringify(data) });
      }
    }
    session.messages.push({ role: 'user', content: results });
  }
  return { reply: 'Не удалось проанализировать прогон.', engine: 'llm' };
}

module.exports = { ask };
