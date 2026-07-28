# Уровень 6 — Next.js (App Router) + TypeScript + PostgreSQL + Prisma + Tailwind

Интернет-магазин цветов: каталог, корзина (zustand + localStorage), оформление заказа
и сохранение заказа в PostgreSQL через Prisma.

## Структура
- `prisma/schema.prisma`, `prisma/seed.ts` — схема БД и тестовые данные
- `src/app/*` — страницы (App Router)
- `src/app/api/*` — API-роуты (`/api/products`, `/api/products/[id]`, `/api/categories`, `/api/orders`, `/api/orders/[id]`)
- `src/components/*`, `src/lib/*`, `src/types/*`, `src/store/*`

> Примечание: папка `src/services/` оставлена как часть структуры из чата, отдельных сервисов там нет.

## Требования
- Node.js 18+ (проверено на Node 22)
- **Работающий сервер PostgreSQL** — SQLite не подойдёт: `schema.prisma` использует
  `provider = "postgresql"` и тип `@db.Decimal(10, 2)`. `DATABASE_URL` обязана указывать на Postgres.

## Настройка

### 1) Переменные окружения
Скопируйте пример и укажите строку подключения к своему PostgreSQL:

```bash
cp .env.example .env
```

`.env` в git не коммитится (см. `.gitignore`), в репозитории лежит только `.env.example`.

```env
DATABASE_URL="postgresql://ПОЛЬЗОВАТЕЛЬ:ПАРОЛЬ@ХОСТ:ПОРТ/БАЗА"
```

Пример для локального dev-сервера:

```env
DATABASE_URL="postgresql://postgres@127.0.0.1:5433/flowers6"
```

База данных должна существовать до запуска Prisma:

```bash
createdb -h 127.0.0.1 -p 5433 -U postgres flowers6
```

### 2) Установка зависимостей

```bash
npm install
```

`postinstall` автоматически выполняет `prisma generate`.

### 3) Создание таблиц и загрузка данных

```bash
npx prisma db push      # или: npx prisma migrate dev
npx prisma db seed      # то же самое, что npm run db:seed
```

Сид создаёт 4 категории и 12 товаров (розы, тюльпаны, букеты, комнатные растения)
и **очищает** существующие заказы/клиентов/товары перед загрузкой.

### 4) Запуск

```bash
npm run dev                 # http://localhost:3000
npm run dev -- -p 3006      # или на другом порту
```

Production-сборка:

```bash
npm run build
npm run start
```

## Проверка API

```bash
curl http://localhost:3000/api/products
curl http://localhost:3000/api/categories

curl -X POST http://localhost:3000/api/orders \
  -H 'Content-Type: application/json' \
  -d '{
    "customer": {
      "name": "Иван Тестовый",
      "phone": "+7 (999) 123-45-67",
      "email": "ivan@example.com",
      "address": "г. Москва, ул. Цветочная, д. 7, кв. 12"
    },
    "items": [{ "productId": 4, "quantity": 3 }],
    "notes": "Позвонить за час до доставки"
  }'
```

Правила валидации (`src/lib/validations.ts`): имя — от 2 символов, телефон — минимум
10 цифр/разделителей, адрес — от 10 символов, минимум одна позиция в `items`.
Заказ создаётся в транзакции: клиент + заказ + позиции, остатки товаров уменьшаются.

## Полезные команды

| Команда | Что делает |
| --- | --- |
| `npm run dev` | dev-сервер Next.js |
| `npm run build` | `prisma generate` + production-сборка |
| `npm run start` | запуск production-сборки |
| `npm run lint` | ESLint (`eslint-config-next`) |
| `npm run type-check` | `tsc --noEmit` |
| `npm run db:push` | синхронизировать схему с БД |
| `npm run db:seed` | загрузить тестовые данные |
| `npm run db:studio` | Prisma Studio |
| `npm run db:migrate` | `prisma migrate dev` |

## Замечания по конфигурации
- `next.config.js` включает `experimental.optimizeCss` — для этого нужен пакет
  `critters` (добавлен в `devDependencies`). Если убрать `critters`, флаг тоже надо убрать.
- Tailwind подключается через `postcss.config.js` (`tailwindcss` + `autoprefixer`).
- Шрифт `Inter` загружается через `next/font/google`, поэтому для первой сборки нужен доступ в интернет.
