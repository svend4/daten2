// student.js — «ученик»: мультиклассовая softmax-регрессия с нуля (без зависимостей).
// Обучение полнобатчевым градиентным спуском при нулевой инициализации →
// детерминированно и воспроизводимо. Инференс дешёвый: b + W·x по активным признакам.
const { featurize, DIM } = require('./features');

function softmax(logits) {
  const m = Math.max(...logits);
  const ex = logits.map((l) => Math.exp(l - m));
  const s = ex.reduce((a, b) => a + b, 0) || 1;
  return ex.map((e) => e / s);
}

function makeModel(labels, dim = DIM) {
  const K = labels.length;
  return { labels, dim, K, W: Array.from({ length: K }, () => new Float64Array(dim)), b: new Float64Array(K) };
}

function logits(model, feats) {
  const out = new Array(model.K);
  for (let k = 0; k < model.K; k++) {
    let s = model.b[k];
    const wk = model.W[k];
    for (const f of feats) s += wk[f.i] * f.v;
    out[k] = s;
  }
  return out;
}

function predict(model, text) {
  const feats = featurize(text, model.dim);
  const p = softmax(logits(model, feats));
  let best = 0;
  for (let k = 1; k < model.K; k++) if (p[k] > p[best]) best = k;
  return { label: model.labels[best], confidence: Math.round(p[best] * 1000) / 1000, probs: Object.fromEntries(model.labels.map((l, k) => [l, Math.round(p[k] * 1000) / 1000])) };
}

// обучение: rows = [{text, label}]; полнобатчевый GD, кросс-энтропия + L2.
function train(labels, rows, { epochs = 250, lr = 0.5, l2 = 1e-4, dim = DIM } = {}) {
  const model = makeModel(labels, dim);
  const idxOf = Object.fromEntries(labels.map((l, i) => [l, i]));
  const data = rows.map((r) => ({ feats: featurize(r.text, dim), y: idxOf[r.label] })).filter((d) => d.y !== undefined);
  const N = data.length || 1;
  // веса классов (обратно частоте) — балансируют влияние редких намерений
  const count = new Float64Array(model.K);
  for (const d of data) count[d.y]++;
  const present = count.filter((c) => c > 0).length || 1;
  const cw = Array.from(count, (c) => (c > 0 ? N / (present * c) : 0));
  const wsum = data.reduce((s, d) => s + cw[d.y], 0) || 1;
  let lastLoss = 0;
  for (let e = 0; e < epochs; e++) {
    const gW = Array.from({ length: model.K }, () => new Float64Array(dim));
    const gb = new Float64Array(model.K);
    let loss = 0;
    for (const d of data) {
      const w = cw[d.y];
      const p = softmax(logits(model, d.feats));
      loss += -w * Math.log(Math.max(1e-12, p[d.y]));
      for (let k = 0; k < model.K; k++) {
        const err = w * (p[k] - (k === d.y ? 1 : 0));
        gb[k] += err;
        if (err !== 0) { const g = gW[k]; for (const f of d.feats) g[f.i] += err * f.v; }
      }
    }
    for (let k = 0; k < model.K; k++) {
      model.b[k] -= lr * (gb[k] / wsum);
      const wk = model.W[k], gk = gW[k];
      for (let j = 0; j < dim; j++) wk[j] -= lr * (gk[j] / wsum + l2 * wk[j]);
    }
    lastLoss = loss / wsum;
  }
  return { model, loss: Math.round(lastLoss * 10000) / 10000, samples: N };
}

// компактная сериализация (обрезаем нули для размера)
function exportModel(model) {
  const W = model.W.map((row) => { const nz = []; for (let j = 0; j < row.length; j++) if (row[j] !== 0) nz.push([j, Math.round(row[j] * 1e5) / 1e5]); return nz; });
  return { labels: model.labels, dim: model.dim, b: Array.from(model.b).map((x) => Math.round(x * 1e5) / 1e5), W };
}
function importModel(obj) {
  const model = makeModel(obj.labels, obj.dim);
  for (let k = 0; k < model.K; k++) { model.b[k] = obj.b[k]; for (const [j, v] of obj.W[k]) model.W[k][j] = v; }
  return model;
}

module.exports = { train, predict, exportModel, importModel, makeModel, softmax };
