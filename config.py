# config.py
import os


class Config:
    """Конфигурация приложения из окружения с безопасными значениями по умолчанию."""

    SECRET_KEY = os.environ.get('SECRET_KEY', 'insecure-dev-key-change-in-production')

    # DEBUG выключен по умолчанию; включается явным DEBUG=true
    DEBUG = os.environ.get('DEBUG', 'false').lower() in ('1', 'true', 'yes')

    # Серверные сессии (корзина) — хранение в файловой системе
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    SESSION_FILE_DIR = os.environ.get('SESSION_FILE_DIR', '/tmp/flask_session')

    # Путь к базе данных
    DATABASE = os.environ.get('DATABASE_PATH', 'flowers.db')
