// advisor.js — LLM-интерпретация бенчмарка (Claude API, цикл tool-use).
// Активен при ANTHROPIC_API_KEY. Инженер спрашивает на естественном языке; Claude
// берёт цифры ТОЛЬКО из инструмента bench_results и объясняет/сравнивает стеки.
const Anthropic = require('@anthropic-ai/sdk');
const store = require('./store');
const bench = require('./bench');

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-8';
const client = new Anthropic();

const SYSTEM = `Ты — SRE-аналитик производительности магазина цветов из семи стеков.
Есть бенчмарк: латентность (p50/p95/p99), пропускная способность (rps), надёжность.
Отвечай на вопросы, опираясь ТОЛЬКО на данные bench_results; сравнивай стеки, называй
самый быстрый/медленный, отмечай offline и просадки. Кратко, по-деловому, по-русски.`;

const TOOLS = [{
  name: 'bench_results',
  description: 'Результаты последнего бенчмарка по каждому стеку: latency_ms (p50/p95/p99/avg/max), throughput_rps, success_ratio, alive, плюс рейтинг.',
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
        const data = run ? { at: run.at, opts: run.opts, results: run.results, ranked: bench.rank(run.results).map((r) => r.id) } : { error: 'бенчмарк ещё не запускался' };
        results.push({ type: 'tool_result', tool_use_id: block.id, content: JSON.stringify(data) });
      }
    }
    session.messages.push({ role: 'user', content: results });
  }
  return { reply: 'Не удалось проанализировать бенчмарк.', engine: 'llm' };
}

module.exports = { ask };
