// rng.js — детерминированный ГПСЧ (mulberry32). Один seed → воспроизводимый прогон,
// поэтому симуляция повторяема (важно для тестов и для честного сравнения what-if).
function makeRng(seed) {
  let a = (seed >>> 0) || 1;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
// целое в [0, n)
const int = (rng, n) => Math.floor(rng() * n);
// выбор индекса по весам
function weighted(rng, weights) {
  const sum = weights.reduce((a, b) => a + b, 0);
  if (sum <= 0) return int(rng, weights.length);
  let r = rng() * sum;
  for (let i = 0; i < weights.length; i++) { r -= weights[i]; if (r < 0) return i; }
  return weights.length - 1;
}

module.exports = { makeRng, int, weighted };
