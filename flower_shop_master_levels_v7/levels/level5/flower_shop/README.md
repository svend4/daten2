# Уровень 5 — React + Flask API + SQLite

Структура (как в чате 14.12.2025):

```
flower_shop/
├── backend/               # Flask API
│   ├── api.py
│   ├── flowers.db
│   └── requirements.txt
│
└── frontend/              # React приложение (Vite)
    ├── package.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx
        └── style.css
```

## Запуск
### Backend
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
python api.py
```

### Frontend
В новом терминале:
```bash
cd frontend
npm install
npm run dev
```

Открыть: http://127.0.0.1:5173
