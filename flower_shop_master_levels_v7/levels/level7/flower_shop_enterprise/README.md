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

## Запуск
Нужен Docker Desktop или Docker Engine.

```bash
docker compose up --build
```

- Витрина через gateway: http://localhost:8080  
- RabbitMQ UI: http://localhost:15672 (логин и пароль: guest, guest)

При создании заказа order-service публикует событие `order.created` в очередь `events`, notification-service выводит его в лог.
