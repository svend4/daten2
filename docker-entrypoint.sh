#!/bin/sh
set -e

# Провижн схемы БД при наличии DATABASE_URL (Render инжектит её в окружение).
# Используем db push, т.к. отдельных миграций в репозитории нет.
if [ -n "$DATABASE_URL" ]; then
  echo "==> Синхронизация схемы БД (prisma db push)..."
  ./node_modules/.bin/prisma db push --skip-generate --accept-data-loss \
    || echo "!! prisma db push не удался — продолжаю запуск (проверьте DATABASE_URL)"
else
  echo "!! DATABASE_URL не задана — пропускаю провижн схемы"
fi

exec node server.js
