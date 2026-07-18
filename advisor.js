// advisor.js — LLM-слой управляющего (Claude API, цикл tool-use).
// Активен при ANTHROPIC_API_KEY. Отвечает управляющему на естественном языке,
// опираясь ТОЛЬКО на числа из детерминированного ядра (инструменты), не выдумывая.
const Anthropic = require('@anthropic-ai/sdk');
const analytics = require('./analytics');
const contract = require('./contract');
const store = require('./store');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const SYSTEM = `Ты — ИИ-управляющий магазина цветов. Помогаешь владельцу: следишь за
остатками, спросом, ценами, аномалиями и дозаказами. Правила:
- Цифры бери ТОЛЬКО из инструментов (get_report, get_products); ничего не выдумывай.
- Опирайся на dailyRate, daysToStockout, reorderPoint, reorderQty, price_suggestion, anomalies.
- Отвечай кратко, по-деловому и по-русски; давай конкретные рекомендации с числами.`;

const TOOLS = [
  { name: 'get_report', description: 'Аналитический отчёт: по каждому товару спрос (dailyRate), прогноз исчерпания (daysToStockout), точка/объём дозаказа, подсказка по цене, аномалии.', input_schema: { type: 'object', properties: {} } },
  { name: 'get_products', description: 'Текущий каталог с ценами и остатками (мгновенный снимок).', input_schema: { type: 'object', properties: {} } },
];

async function runTool(name) {
  if (name === 'get_report') return analytics.report(store.all());
  if (name === 'get_products') return contract.listProducts();
  return { error: 'unknown tool' };
}

async function ask(session, text) {
  session.messages = session.messages || [];
  session.messages.push({ role: 'user', content: text });
  let guard = 0;
  while (guard++ < 8) {
    const resp = await client.messages.create({ model: MODEL, max_tokens: 1024, system: SYSTEM, tools: TOOLS, messages: session.messages });
    session.messages.push({ role: 'assistant', content: resp.content });
    if (resp.stop_reason !== 'tool_use') {
      const out = resp.content.filter((b) => b.type === 'text').map((b) => b.text).join('\n');
      return { reply: out || '(нет ответа)', engine: 'llm' };
    }
    const results = [];
    for (const block of resp.content) {
      if (block.type === 'tool_use') {
        let r;
        try { r = await runTool(block.name); } catch (e) { r = { error: String(e.message) }; }
        results.push({ type: 'tool_result', tool_use_id: block.id, content: JSON.stringify(r) });
      }
    }
    session.messages.push({ role: 'user', content: results });
  }
  return { reply: 'Не удалось завершить анализ.', engine: 'llm' };
}

module.exports = { ask };
