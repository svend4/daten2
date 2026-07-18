# Слой наблюдаемости · бенчмарк 7 стеков (Observability)

Наблюдаемость над семью уровнями магазина: **нагрузочный бенчмарк каждого стека
через единый контракт** и сравнение «в лоб» — латентность (p50/p95/p99),
пропускная способность (rps), надёжность. Метрики отдаются в формате **Prometheus**
(`/metrics`), результаты — в дашборде и через API. Так как все уровни говорят на
одном контракте, они **сравнимы напрямую**.

```
        ┌── /api/products ──▶ L1 (PHP)
бенчмарк ├── /api/products ──▶ L2 (Flask)      →  p50/p95/p99 · rps · success
(N×C)    ├── ...                               →  рейтинг + /metrics + интерпретация
        └── /api/products ──▶ L7 (Microservices)
```

## Что измеряется

Для каждого стека прогоняется `requests` запросов при параллелизме `concurrency`
по выбранному эндпоинту (по умолчанию **только чтение** — `/api/products` или
`/api/health`, без побочных эффектов на живом магазине):

| Метрика | Смысл |
|---------|-------|
| `latency_ms.p50/p95/p99/avg/max/min` | распределение времени ответа |
| `throughput_rps` | успешных запросов в секунду (учёт реальной параллельности) |
| `success_ratio` | доля успешных ответов (0..1) |
| `alive` | ответил ли стек на `/api/health` |

Рейтинг: живые и надёжные вперёд, затем по p95, затем по throughput.

## Метрики Prometheus (`/metrics`)

```
flowershop_bench_up{level="level2",stack="Flask"} 1
flowershop_bench_latency_ms{level="level2",stack="Flask",quantile="p95"} 42.7
flowershop_bench_throughput_rps{level="level2",stack="Flask"} 610
flowershop_bench_success_ratio{level="level2",stack="Flask"} 1
```

Готово к скрейпу Prometheus / визуализации в Grafana.

## Два движка интерпретации, одно ядро

`POST /api/ask` — инженер спрашивает о результатах:

| Движок | Когда | Что делает |
|--------|-------|------------|
| **`llm`** (Claude API) | задан `ANTHROPIC_API_KEY` | Claude сравнивает стеки, беря цифры **только** из инструмента `bench_results` (`claude-opus-4-8`) |
| **`rules`** | ключа нет | Детерминированные ответы: самый быстрый/медленный, throughput, проблемные, таблица |

Ядро бенчмарка всегда детерминировано; LLM лишь озвучивает выводы.

## Запуск

```bash
npm install
# список стеков (иначе локальные значения по умолчанию L1…L7):
export OBS_LEVELS='[{"id":"level1","name":"PHP","url":"http://localhost:8081"},
                    {"id":"level2","name":"Flask","url":"http://localhost:8082"}]'
# export ANTHROPIC_API_KEY=sk-ant-...   # включить LLM-аналитика
npm start                                # → http://localhost:8074
```

Дашборд: выбор эндпоинта/нагрузки, кнопка «Прогнать бенчмарк», таблица сравнения
со шкалами латентности и throughput, ссылка на `/metrics`, чат с аналитиком.

## API

| Метод | Путь | Назначение |
|-------|------|------------|
| `GET`  | `/api/health`  | `{ ok, engine, levels, hasRun }` |
| `GET`  | `/api/levels`  | список стеков |
| `POST` | `/api/bench`   | `{ path, requests, concurrency }` → прогон по всем стекам |
| `GET`  | `/api/results` | последний прогон + рейтинг |
| `GET`  | `/metrics`     | метрики Prometheus (text) |
| `POST` | `/api/ask`     | `{ sessionId, message }` → интерпретация |

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `OBS_LEVELS` | локальные L1…L7 | Стеки для бенчмарка (JSON) |
| `ROUTER_URL` | — | (опц.) адрес роутера для пассивного наблюдения |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — / `claude-opus-4-8` | LLM-аналитик |
| `PORT` | `8074` | Порт |

## Тест

```bash
npm test
```

`test/smoke.mjs` поднимает четыре живых mock-стека (быстрый, медленный, flaky с
половиной 500, offline) и проверяет корректность бенчмарка (p95, throughput,
success), рейтинг (быстрый — первый, offline — последний), формат `/metrics` и
детерминированную интерпретацию. Без сети и ключа. 19/19.

## Файлы

| Файл | Роль |
|------|------|
| `bench.js` | Ядро: нагрузка, перцентили, throughput, success, рейтинг |
| `metrics.js` | Рендер последнего прогона в формат Prometheus |
| `store.js` | Последний прогон в памяти |
| `registry.js` | Стеки-кандидаты (`OBS_LEVELS` или по умолчанию) |
| `advisor.js` | LLM-аналитик (цикл tool-use Claude API) |
| `interpret.js` | Детерминированная интерпретация (фолбэк) |
| `server.js` | Express: `/api/bench`, `/api/results`, `/metrics`, `/api/ask` |
| `public/index.html` | Дашборд сравнения стеков |
| `test/smoke.mjs` | Смоук-тест бенчмарка и метрик |
