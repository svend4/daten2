# Уровень 7 — Enterprise: микросервисы (Docker + nginx gateway + Postgres + RabbitMQ)

Структура (по описанию в чате 14.12.2025):

```
flower_shop_enterprise/
├── frontend/                    # React приложение (Vite)
├── api-gateway/                 # nginx конфиг (reverse proxy)
├── services/
│   ├── product-service/         # Микросервис товаров (Node.js)
│   ├── order-service/           # Микросервис заказов (Python)
│   └── notification-service/    # Уведомления (consumer очереди)
├── db/
│   └── init.sql                 # Инициализация Postgres + seed
└── docker-compose.yml
```

## Запуск (полный стек — docker-compose)
Нужен Docker Desktop или Docker Engine. Файл: `docker-compose.local.yml`.

```bash
docker compose -f docker-compose.local.yml up --build
```

- Витрина через gateway: http://localhost:8080
- RabbitMQ UI: http://localhost:15672 (логин и пароль: guest, guest)

Маршрутизация gateway (nginx слушает контейнерный порт 80, наружу `8080:80`):
`/api/products` → `product-service:3001`, `/api/orders` → `order-service:8000`, `/` → `frontend:5173`.
Брокер передаётся через `RABBITMQ_URL`. При создании заказа order-service публикует
событие `order.created` в очередь `events`, notification-service выводит его в лог.

## Деплой на Render (ограничение)
Render запускает один сервис из корневого `Dockerfile` — он поднимает **только фронтенд** (Vite).
Бэкенд, Postgres и RabbitMQ при этом не разворачиваются, поэтому онлайн-витрина покажет
пустой каталог. Полноценный запуск — только через `docker-compose.local.yml` выше
(или разнести сервисы по отдельным Render-сервисам + управляемые Postgres/RabbitMQ).
