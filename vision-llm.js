// vision-llm.js — Claude-vision (мультимодальный анализ). Активен при ANTHROPIC_API_KEY.
// Понимает любой формат (JPEG/PNG/WebP/GIF), даёт богатые теги и описание товара.
const Anthropic = require('@anthropic-ai/sdk');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const TOOL = {
  name: 'describe_bouquet',
  description: 'Описать изображение цветов: тип, цвет, теги, повод.',
  input_schema: {
    type: 'object',
    properties: {
      flower: { type: 'string', description: 'основной вид цветка (роза/тюльпан/пион/…)' },
      color: { type: 'string' },
      tags: { type: 'array', items: { type: 'string' } },
      occasion: { type: 'string', description: 'подходящий повод' },
      description: { type: 'string', description: 'продающее описание для карточки товара (RU)' },
    },
    required: ['flower', 'color', 'tags', 'description'],
  },
};

// mediaType: 'image/jpeg' | 'image/png' | 'image/webp' | 'image/gif'
async function analyze(base64, mediaType = 'image/png') {
  const resp = await client.messages.create({
    model: MODEL, max_tokens: 512, tools: [TOOL],
    tool_choice: { type: 'tool', name: 'describe_bouquet' },
    messages: [{
      role: 'user',
      content: [
        { type: 'image', source: { type: 'base64', media_type: mediaType, data: base64 } },
        { type: 'text', text: 'Опиши эти цветы для интернет-магазина.' },
      ],
    }],
  });
  const call = resp.content.find((b) => b.type === 'tool_use');
  return call ? { ...call.input, engine: 'llm' } : { error: 'не удалось распознать', engine: 'llm' };
}

module.exports = { analyze };
