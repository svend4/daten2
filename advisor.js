// advisor.js — LLM-объяснение работы автономной петли (Claude API, цикл tool-use).
// Активен при ANTHROPIC_API_KEY. Факты — ТОЛЬКО из инструмента loop_state.
const Anthropic = require('@anthropic-ai/sdk');
const store = require('./store');
const policy = require('./policy');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const SYSTEM = `Ты — помощник владельца магазина цветов, объясняющий работу
АВТОНОМНОГО управляющего. Петля сама выполняет безопасные действия (дозаказ,
пометка аномалий) и эскалирует человеку рискованные (смена цены, крупные закупки).
Отвечай, опираясь ТОЛЬКО на loop_state (очередь одобрений, журнал, аудит, режим).
Кратко, по-деловому, по-русски. Рекомендуй одобрить/отклонить, если спрашивают.`;

const TOOLS = [{
  name: 'loop_state',
  description: 'Состояние петли: режим (пауза/сухой прогон, пороги), pending (очередь одобрений), ledger (выполненное), audit (события).',
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
        const data = {
          mode: { ...store.state(), autoThreshold: policy.autoThreshold, maxActionsPerCycle: policy.maxActionsPerCycle, cooldownCycles: policy.cooldownCycles },
          pending: store.pendingList, ledger: store.ledgerList.slice(-15), audit: store.auditList.slice(-20),
        };
        results.push({ type: 'tool_result', tool_use_id: block.id, content: JSON.stringify(data) });
      }
    }
    session.messages.push({ role: 'user', content: results });
  }
  return { reply: 'Не удалось объяснить состояние петли.', engine: 'llm' };
}

module.exports = { ask };
