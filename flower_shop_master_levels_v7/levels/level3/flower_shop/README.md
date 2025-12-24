# Уровень 3 — Django + админка

Структура (как в чате 14.12.2025):

```
flower_shop/
├── manage.py
├── flower_shop/           # Настройки проекта
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── shop/                  # Приложение магазина
│   ├── models.py          # Модели БД
│   ├── views.py
│   └── admin.py           # Админка
├── templates/
│   └── index.html
└── static/
    └── style.css
```

## Запуск
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

- Сайт: http://127.0.0.1:8000  
- Админка: http://127.0.0.1:8000/admin/  
Добавьте категории и товары в админке — они появятся на главной.
