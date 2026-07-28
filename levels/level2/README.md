# Уровень 2 — Flask + SQLite + шаблоны

Структура:

```
flower_shop/
├── app.py                 # Backend: маршруты (каталог, товар, корзина, заказ)
├── config.py              # Настройки (SECRET_KEY, DEBUG, PORT, сессия)
├── database.py            # Работа с SQLite (товары, категории, заказы)
├── flowers.db             # База данных (SQLite, уже заполнена)
├── requirements.txt       # Зависимости (только Flask)
├── templates/             # HTML шаблоны (Jinja2)
│   ├── index.html         # Каталог + поиск + категории
│   ├── product.html       # Страница товара
│   ├── cart.html          # Корзина (хранится в сессии)
│   ├── checkout.html      # Оформление заказа
│   ├── order_success.html # Заказ оформлен
│   ├── 404.html
│   └── 500.html
├── static/                # CSS, изображения
│   ├── style.css
│   └── images/
│       ├── rose.jpg
│       ├── tulip.jpg
│       └── peony.jpg
```

## Запуск
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux или Mac: source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Открыть: http://127.0.0.1:5000

Другой порт (переменная окружения `PORT`):

```bash
PORT=5002 python app.py      # Linux / Mac
# Windows PowerShell: $env:PORT=5002; python app.py
```

## Как это работает
- Корзина хранится в обычной сессии Flask (подписанная cookie), поэтому
  дополнительных библиотек, кроме Flask, не нужно — нужен только `SECRET_KEY`
  из `config.py`.
- Все запросы к базе собраны в `database.py`, маршруты — в `app.py`.
- При первом импорте `database.py` в таблицу `orders` добавляются недостающие
  колонки (`email`, `address`, `total_amount`) через `ALTER TABLE` —
  существующие товары и категории при этом сохраняются.

## Что попробовать
1. Открыть каталог, найти товар через поиск или фильтр по категории.
2. Добавить товар в корзину, изменить состав корзины.
3. Оформить заказ — он появится в таблицах `orders` и `order_items`:

```bash
sqlite3 flowers.db "SELECT * FROM orders;"
```
