# Уровень 2 — Flask + SQLite + шаблоны

Структура (как в чате 14.12.2025):

```
flower_shop/
├── app.py                 # Backend
├── flowers.db             # База данных (SQLite, уже заполнена)
├── templates/             # HTML шаблоны
│   └── index.html
├── static/                # CSS, JS, изображения
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
# Linux/Mac: source .venv/bin/activate

pip install flask
python app.py
```

Открыть: http://127.0.0.1:5000


## Установка
```bash
pip install -r requirements.txt
```
