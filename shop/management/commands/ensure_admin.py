"""Идемпотентно создаёт суперпользователя из окружения.

Безопасно по умолчанию: без ADMIN_PASSWORD ничего не создаётся (в проде
администратор не заводится автоматически со слабым паролем).

  ADMIN_USERNAME=admin ADMIN_PASSWORD=... ADMIN_EMAIL=a@b.c \
      python manage.py ensure_admin
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Создаёт/обновляет суперпользователя из ADMIN_* переменных окружения'

    def handle(self, *args, **options):
        password = os.environ.get('ADMIN_PASSWORD')
        if not password:
            self.stdout.write('ADMIN_PASSWORD не задан — суперпользователь не создаётся')
            return

        username = os.environ.get('ADMIN_USERNAME', 'admin')
        email = os.environ.get('ADMIN_EMAIL', '')
        User = get_user_model()

        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'is_staff': True, 'is_superuser': True},
        )
        user.email = email or user.email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        verb = 'создан' if created else 'обновлён'
        self.stdout.write(self.style.SUCCESS(f'Суперпользователь «{username}» {verb}'))
