# Реальные интеграции · адаптеры (Integrations)

Внешние сервисы через **адаптеры с двойным движком**: реальный провайдер при наличии
ключа, иначе **детерминированный mock** (демо и тесты работают без ключа и без сети).
Два адаптера:

- **💳 Платежи** — Stripe при `STRIPE_SECRET_KEY`, иначе mock.
- **🧭 Эмбеддинги** — Voyage AI при `VOYAGE_API_KEY`, иначе mock. *(У Anthropic нет
  embeddings-API — стандартный выбор для векторов Voyage.)*

Оба провайдера реализуют **один интерфейс**, поэтому остальной код не знает, реальный
это сервис или mock — переключение прозрачно (тот же принцип, что «контракт как
граница» на уровне провайдеров).

## 💳 Платежи

Интерфейс: `createIntent(amount, currency, orderNumber)` → `confirm(intentId)` →
`get(intentId)`. Статусы `requires_confirmation → succeeded`. Stripe-адаптер ходит в
`api.stripe.com/v1/payment_intents` (raw HTTPS, суммы в центах, `order_number` в
metadata); mock — детерминированный in-memory.

## 🧭 Эмбеддинги и семантическая близость

Интерфейс: `embed(texts[]) → vectors[]` + косинусное ранжирование `rank(query, docs)`.
Voyage-адаптер вызывает `api.voyageai.com/v1/embeddings`; mock — **детерминированные**
хэш-фичи (униграммы+биграммы, L2-нормировка): один текст → один вектор, косинус
осмыслен по общим токенам. `/api/similarity` ранжирует документы по близости.

## Запуск

```bash
npm install
# без ключей — mock-провайдеры (полностью функционально):
npm start                              # → http://localhost:8101
# реальные провайдеры:
export STRIPE_SECRET_KEY=sk_test_...   # платежи → Stripe
export VOYAGE_API_KEY=pa-...           # эмбеддинги → Voyage
```

Дашборд: создание+подтверждение платежа и семантическое ранжирование документов; бейджи
показывают активного провайдера (mock/real).

## API

| Метод | Путь | Назначение |
|-------|------|------------|
| `GET`  | `/api/health` / `/api/providers` | активные провайдеры (mock/real) |
| `POST` | `/api/payments/intent` | `{ amount, currency, orderNumber }` → intent |
| `POST` | `/api/payments/confirm` | `{ intentId }` → succeeded |
| `GET`  | `/api/payments/:id` | статус платежа |
| `POST` | `/api/embed` | `{ texts }` → `{ model, dim, vectors }` |
| `POST` | `/api/similarity` | `{ query, docs }` → ранжирование по косинусу |
| `POST` | `/api/ask` | сводка по интеграциям |

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `STRIPE_SECRET_KEY` | — | Включает реальный Stripe (иначе mock) |
| `VOYAGE_API_KEY` / `VOYAGE_MODEL` | — / `voyage-3` | Включает реальный Voyage (иначе mock) |
| `EMBED_DIM` | `256` | Размерность mock-эмбеддингов |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — / `claude-opus-4-8` | LLM-сводка |
| `PORT` | `8101` | Порт |

## Тест

```bash
npm test
```

`test/smoke.mjs` (без ключей → mock) проверяет: выбор провайдера, платёжный поток
(intent → confirm → status; сумма/валюта; ошибка на неизвестный intent),
**детерминированные** эмбеддинги (тот же текст → тот же L2-нормированный вектор),
косинусное ранжирование (релевантный документ вверху), и HTTP. Без сети и ключа. 20/20.

## Файлы

| Файл | Роль |
|------|------|
| `payment/index.js` | Выбор провайдера платежей (Stripe|mock) |
| `payment/stripe.js` · `payment/mock.js` | Реальный Stripe и детерминированный mock |
| `embeddings/index.js` | Выбор провайдера + косинус + ранжирование |
| `embeddings/voyage.js` · `embeddings/mock.js` | Реальный Voyage и детерминированный mock |
| `server.js` | Express: `/api/payments/*`, `/api/embed`, `/api/similarity` |
| `interpret.js` | Сводка по активным провайдерам |
| `public/index.html` | Дашборд платежей и семантического поиска |
| `test/smoke.mjs` | Смоук-тест адаптеров на mock-провайдерах |
