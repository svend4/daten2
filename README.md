# 🌹 Магазин цветов — один магазин в 7 уровнях сложности

Это учебный репозиторий: **один и тот же** интернет-магазин цветов (каталог → корзина → заказ),
переписанный семь раз — от одного PHP-файла до архитектуры из микросервисов.
Каждая ступень добавляет ровно один инженерный приём.

## Структура

```
.
├── backend/ + frontend/ + Dockerfile   # Уровень 5 в корне — то, что деплоится (Render)
└── levels/
    ├── level1/   PHP + SQLite
    ├── level2/   Flask + SQLite + Jinja2
    ├── level3/   Django (ORM, админка)
    ├── level4/   Node.js + Express + EJS
    ├── level5/   React (Vite) + Flask API
    ├── level6/   Next.js + TypeScript + Prisma + PostgreSQL + Tailwind
    └── level7/   Микросервисы: nginx + Node + Flask + PostgreSQL + RabbitMQ
```

> Уровень 5 лежит и в корне (как цель деплоя), и в `levels/level5/` — чтобы все семь
> уровней можно было изучать и запускать единообразно.

## Уровни

| Ур. | Стек | Рендеринг | Хранилище | Корзина |
|----|------|-----------|-----------|---------|
| 1 | PHP + SQLite | сервер (PHP) | SQLite | POST-форма |
| 2 | Flask + Jinja2 | сервер (Python) | SQLite | серверная сессия |
| 3 | Django | сервер (Python) | SQLite через ORM | сессия |
| 4 | Express + EJS | сервер (Node) | SQLite | форма |
| 5 | React SPA + Flask API | клиент (SPA) | SQLite | состояние React |
| 6 | Next.js + Prisma | гибрид (SSR + CSR) | PostgreSQL | Zustand store |
| 7 | Микросервисы | клиент + сервисы | PostgreSQL | состояние + API |

Во всех уровнях один и тот же ассортимент: **Красная роза 7,90 €**, **Букет тюльпанов 19,90 €**,
**Пион (шт.) 9,50 €**.

## Запуск

### Уровень 1 — PHP
```bash
cd levels/level1
php -S 127.0.0.1:8081        # http://127.0.0.1:8081/index.php
```
База `flowers.db` уже заполнена. Пересоздать с нуля: открыть `init_db.php`.

### Уровень 2 — Flask
```bash
cd levels/level2
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python app.py                 # http://127.0.0.1:5000
```

### Уровень 3 — Django
```bash
cd levels/level3
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed         # наполнить каталог
python manage.py runserver    # http://127.0.0.1:8000
```
Админка: `python manage.py createsuperuser`, затем `/admin/`.

### Уровень 4 — Node.js + Express
```bash
cd levels/level4
npm install
npm start                     # http://127.0.0.1:3000
```

### Уровень 5 — React + Flask API
```bash
# терминал 1 — API
cd levels/level5/backend
pip install -r requirements.txt
python api.py                 # http://127.0.0.1:5001

# терминал 2 — фронтенд
cd levels/level5/frontend
npm install && npm run dev    # http://127.0.0.1:5173
```

### Уровень 6 — Next.js + Prisma + PostgreSQL
Нужен работающий PostgreSQL. Скопируйте `.env.example` в `.env` и укажите `DATABASE_URL`.
```bash
cd levels/level6
npm install
npx prisma generate
npx prisma db push
npm run db:seed
npm run dev                   # http://127.0.0.1:3000
```

### Уровень 7 — микросервисы
```bash
cd levels/level7
docker compose up --build     # витрина через шлюз: http://localhost:8080
```
Без Docker сервисы поднимаются вручную: PostgreSQL (схема `db/init.sql`), RabbitMQ,
затем `product-service` (:7001), `order-service` (:7002), `frontend` (:5173) и nginx
по конфигу `api-gateway/nginx.conf`.

При создании заказа `order-service` публикует событие `order.created` в очередь `events`,
а `notification-service` читает её и пишет уведомление в лог.

## Как устроен каждый уровень

- **1 → 2.** Появляется разделение ответственности: маршруты, шаблоны и слой данных (`database.py`) разъезжаются по файлам, корзина живёт в серверной сессии.
- **2 → 3.** Фреймворк берёт на себя рутину: ORM вместо сырого SQL, миграции, готовая админка.
- **3 → 4.** Тот же серверный рендеринг, но на JavaScript — один язык на бэкенде и фронтенде.
- **4 → 5.** Настоящее разделение клиент/сервер: SPA на React общается с REST API по JSON.
- **5 → 6.** Типобезопасность (TypeScript), декларативная схема БД (Prisma), PostgreSQL, utility-CSS.
- **6 → 7.** Монолит распадается на независимые сервисы за API-шлюзом, а заказы порождают асинхронные события через очередь.
