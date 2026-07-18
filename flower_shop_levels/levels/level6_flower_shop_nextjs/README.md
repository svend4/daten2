# Уровень 6 — Next.js (App Router) + TypeScript + PostgreSQL + Prisma + Tailwind

Этот проект **собран по коду из чата за 14.12.2025** (без учёта изменений 17.12).

## Структура (как в чате)
- `prisma/schema.prisma`, `prisma/seed.ts`
- `src/app/*` (App Router)
- `src/app/api/*` (API routes)
- `src/components/*`, `src/lib/*`, `src/types/*`, `src/store/*`

> Примечание: в дереве структуры в чате упоминалась папка `src/services/`, но отдельных блоков кода для `productService.ts` и `orderService.ts` в сообщениях 14.12 не было — папка оставлена как часть структуры.

## Быстрый запуск
1) Поднимите PostgreSQL и задайте `DATABASE_URL` в `.env`
2) Установите зависимости:
```bash
npm install
```
3) Prisma:
```bash
npx prisma generate
npx prisma migrate dev
npx prisma db seed
```
4) Запуск:
```bash
npm run dev
```
Открыть: http://localhost:3000
