// llm-agent.js — LLM-стратегия агента (Claude API). Активна при ANTHROPIC_API_KEY.
// Claude играет роль покупателя ИЛИ продавца, выбирая цену в допустимых границах;
// границы — жёсткие (пол/потолок), поэтому LLM не может нарушить политику.
const Anthropic = require('@anthropic-ai/sdk');
const { round2 } = require('./protocol');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'offer',
  description: 'Предложить цену за единицу в допустимых границах и решить, принимать ли текущее предложение.',
  input_schema: {
    type: 'object',
    properties: {
      price: { type: 'number', description: 'предлагаемая цена за единицу' },
      accept: { type: 'boolean', description: 'принять текущее предложение оппонента' },
      note: { type: 'string' },
    },
    required: ['price', 'accept'],
  },
};

// role: 'buyer'|'seller'; bounds: {min,max}; ставит цену в границах.
function makeLlmAgent(role, bounds, product) {
  const SYSTEM = role === 'buyer'
    ? `Ты — агент-покупатель цветов. Торгуйся за минимальную цену, но не выше ${bounds.max} € за «${product.name}». Цена всегда в [${bounds.min}, ${bounds.max}].`
    : `Ты — агент-продавец. Торгуйся за максимальную цену, но не ниже ${bounds.min} € за «${product.name}». Цена всегда в [${bounds.min}, ${bounds.max}].`;
  return {
    role,
    async decide(opponentPrice) {
      const resp = await client.messages.create({
        model: MODEL, max_tokens: 256, system: SYSTEM, tools: [TOOL],
        tool_choice: { type: 'tool', name: 'offer' },
        messages: [{ role: 'user', content: `Предложение оппонента: ${opponentPrice} €. Твой ход.` }],
      });
      const call = resp.content.find((b) => b.type === 'tool_use');
      const price = Math.max(bounds.min, Math.min(bounds.max, Number(call && call.input && call.input.price) || opponentPrice));
      return { price: round2(price), accept: !!(call && call.input && call.input.accept), note: (call && call.input && call.input.note) || '' };
    },
  };
}

module.exports = { makeLlmAgent };
