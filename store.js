// store.js — обученная модель ученика + метрики в памяти.
let current = null; // { model, metrics, at }
const set = (v) => { current = v; return current; };
const get = () => current;
module.exports = { set, get };
