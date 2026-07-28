# config.py — настройки приложения
import os


class Config:
    """Настройки Flask-приложения (уровень 2)."""

    # Секретный ключ нужен для подписи cookie-сессии (корзина хранится в сессии).
    # В учебном проекте есть значение по умолчанию, на реальном сервере
    # задайте переменную окружения SECRET_KEY.
    SECRET_KEY = os.environ.get('SECRET_KEY', 'flower-shop-secret-key-level2')

    # Режим отладки: автоперезагрузка и подробные ошибки
    DEBUG = os.environ.get('DEBUG', '1') == '1'

    # Порт, на котором запускается сервер
    PORT = int(os.environ.get('PORT', 5000))

    # Файл базы данных SQLite (лежит рядом с app.py)
    DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flowers.db')

    # Настройки сессии: обычная подписанная cookie-сессия Flask
    SESSION_COOKIE_NAME = 'flower_shop_session'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7  # 7 дней
