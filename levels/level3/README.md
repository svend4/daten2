# Уровень 3 — Django + админка

Структура (как в чате 14.12.2025):

```
flower_shop/
├── manage.py
├── flowers.db             # SQLite с готовыми цветами (уже в репозитории)
├── flower_shop/           # Настройки проекта
│   ├── settings.py
│   ├── urls.py            # admin/ + include('shop.urls')
│   └── wsgi.py
├── shop/                  # Приложение магазина
│   ├── models.py          # Category, Product, Customer, Order, OrderItem
│   ├── views.py           # каталог, товар, корзина, оформление заказа
│   ├── forms.py           # AddToCartForm, CheckoutForm
│   ├── urls.py            # маршруты с app_name = 'shop'
│   ├── admin.py           # Админка
│   ├── migrations/        # Миграции (в репозитории)
│   └── management/commands/seed.py   # Наполнение базы товарами
├── templates/
│   ├── index.html         # старый одиночный шаблон, оставлен для истории
│   ├── base.html          # общий каркас + сообщения (messages)
│   └── shop/
│       ├── index.html         # каталог (поиск и пагинация)
│       ├── product_detail.html
│       ├── cart.html
│       ├── checkout.html
│       └── order_success.html
└── static/
    └── style.css
```

## Запуск
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux или Mac: source .venv/bin/activate

pip install -r requirements.txt
python manage.py migrate          # flowers.db уже есть, миграции просто отмечаются
python manage.py runserver
```

Открыть: http://127.0.0.1:8000

Если база пустая (например, вы удалили `flowers.db`), товары добавит команда:

```bash
python manage.py seed
```

Она создаёт те же цветы, что и на других уровнях:
Красная роза 7.90 €, Букет тюльпанов 19.90 €, Пион (шт.) 9.50 €.
Команду можно запускать повторно — дубликатов не будет.

## Админка
```bash
python manage.py createsuperuser
```
- Сайт: http://127.0.0.1:8000
- Админка: http://127.0.0.1:8000/admin/

В админке можно добавлять категории и товары и смотреть заказы.
Картинки товаров (`Product.image`) загружаются в папку `media/` (нужен Pillow).

## Как это работает
- `/` — каталог (`ProductListView`, по 12 товаров на страницу, поиск `?search=роза`)
- `/product/<slug>/` — карточка товара
- `/category/<slug>/` — товары одной категории
- `/cart/` — корзина, она хранится в сессии Django
- `/checkout/` — оформление: создаются `Customer`, `Order`, `OrderItem`,
  остатки на складе уменьшаются
- `/order/<id>/` — страница оформленного заказа
