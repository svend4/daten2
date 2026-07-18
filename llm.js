// llm.js — разговорный движок на Claude API (tool-use цикл).
// Активен, когда задан ANTHROPIC_API_KEY. Инструменты = единый контракт магазина.
const Anthropic = require('@anthropic-ai/sdk');
const shop = require('./shop');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic(); // читает ANTHROPIC_API_KEY из окружения

const SYSTEM = `Ты — дружелюбный ассистент интернет-магазина цветов. Помогаешь покупателю
выбрать букет и оформить заказ. Правила:
- Для каталога и заказов ВСЕГДА используй инструменты; цены бери только с сервера, не выдумывай.
- Оформляй заказ (create_order) лишь когда покупатель явно подтвердил покупку и назвал имя.
- Отвечай кратко и по-русски.`;

const TOOLS = [
  {
    name: 'list_products',
    description: 'Вернуть каталог активных товаров магазина (id, name, price, currency, stock, is_featured, category_name).',
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'create_order',
    description: 'Оформить заказ. Возвращает order_number (токен) и total. Вызывай только после явного подтверждения покупателя.',
    input_schema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Имя покупателя' },
        phone: { type: 'string' },
        email: { type: 'string' },
        address: { type: 'string' },
        items: {
          type: 'array',
          items: {
            type: 'object',
            properties: { product_id: { type: 'integer' }, quantity: { type: 'integer' } },
            required: ['product_id', 'quantity'],
          },
        },
      },
      required: ['name', 'items'],
    },
  },
  {
    name: 'get_order',
    description: 'Получить статус и состав заказа по непубличному номеру (токену).',
    input_schema: { type: 'object', properties: { order_number: { type: 'string' } }, required: ['order_number'] },
  },
];

async function runTool(name, input) {
  if (name === 'list_products') return shop.listProducts();
  if (name === 'create_order') return shop.createOrder(input);
  if (name === 'get_order') return shop.getOrder(input.order_number);
  return { error: 'unknown tool' };
}

async function handle(session, text) {
  session.messages = session.messages || [];
  session.messages.push({ role: 'user', content: text });

  let guard = 0;
  while (guard++ < 8) {
    const resp = await client.messages.create({
      model: MODEL, max_tokens: 1024, system: SYSTEM, tools: TOOLS, messages: session.messages,
    });
    session.messages.push({ role: 'assistant', content: resp.content });

    if (resp.stop_reason !== 'tool_use') {
      const out = resp.content.filter((b) => b.type === 'text').map((b) => b.text).join('\n');
      return { reply: out || '(нет ответа)', engine: 'llm' };
    }

    const toolResults = [];
    for (const block of resp.content) {
      if (block.type === 'tool_use') {
        let result;
        try { result = await runTool(block.name, block.input); }
        catch (e) { result = { error: String(e.message) }; }
        toolResults.push({ type: 'tool_result', tool_use_id: block.id, content: JSON.stringify(result) });
      }
    }
    session.messages.push({ role: 'user', content: toolResults });
  }
  return { reply: 'Извините, не удалось завершить запрос.', engine: 'llm' };
}

module.exports = { handle };
