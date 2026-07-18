// metrics.js — рендер последнего прогона в текстовый формат Prometheus (/metrics).
const store = require('./store');

function render() {
  const run = store.get();
  const lines = [];
  const push = (name, help, type) => { lines.push(`# HELP ${name} ${help}`); lines.push(`# TYPE ${name} ${type}`); };

  push('flowershop_bench_up', 'Уровень доступен во время бенчмарка (1/0)', 'gauge');
  if (run) for (const r of run.results) lines.push(`flowershop_bench_up{level="${r.id}",stack="${r.name}"} ${r.alive ? 1 : 0}`);

  push('flowershop_bench_latency_ms', 'Латентность запроса по перцентилям (мс)', 'gauge');
  if (run) for (const r of run.results) {
    if (!r.alive) continue;
    for (const stat of ['p50', 'p95', 'p99', 'avg', 'max']) {
      const v = r.latency_ms[stat];
      if (v != null) lines.push(`flowershop_bench_latency_ms{level="${r.id}",stack="${r.name}",quantile="${stat}"} ${v}`);
    }
  }

  push('flowershop_bench_throughput_rps', 'Пропускная способность (успешных запросов/с)', 'gauge');
  if (run) for (const r of run.results) if (r.alive) lines.push(`flowershop_bench_throughput_rps{level="${r.id}",stack="${r.name}"} ${r.throughput_rps}`);

  push('flowershop_bench_success_ratio', 'Доля успешных запросов (0..1)', 'gauge');
  if (run) for (const r of run.results) if (r.alive) lines.push(`flowershop_bench_success_ratio{level="${r.id}",stack="${r.name}"} ${r.success_ratio}`);

  push('flowershop_bench_requests_total', 'Всего запросов в последнем прогоне', 'gauge');
  if (run) for (const r of run.results) lines.push(`flowershop_bench_requests_total{level="${r.id}",stack="${r.name}"} ${r.requests}`);

  return lines.join('\n') + '\n';
}

module.exports = { render };
