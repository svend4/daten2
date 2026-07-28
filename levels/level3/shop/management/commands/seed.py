# shop/management/commands/seed.py
"""Наполнение базы теми же цветами, что и на других уровнях.

Запуск:  python manage.py seed
Команду можно выполнять повторно — товары не дублируются.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from shop.models import Category, Product

CATEGORIES = [
    ('Розы', 'roses'),
    ('Тюльпаны', 'tulips'),
    ('Пионы', 'peonies'),
]

PRODUCTS = [
    ('Красная роза', 'red-rose', 'Классическая красная роза.', Decimal('7.90'), 'roses', 50),
    ('Букет тюльпанов', 'tulip-bouquet', 'Букет из 9 тюльпанов.', Decimal('19.90'), 'tulips', 30),
    ('Пион (шт.)', 'peony', 'Пышный пион.', Decimal('9.50'), 'peonies', 25),
]


class Command(BaseCommand):
    help = 'Добавляет категории и товары магазина цветов'

    def handle(self, *args, **options):
        for name, slug in CATEGORIES:
            category, created = Category.objects.get_or_create(
                slug=slug, defaults={'name': name}
            )
            if created:
                self.stdout.write(f'Категория добавлена: {category.name}')

        for name, slug, description, price, category_slug, stock in PRODUCTS:
            product, created = Product.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'description': description,
                    'price': price,
                    'category': Category.objects.get(slug=category_slug),
                    'stock': stock,
                },
            )
            if created:
                self.stdout.write(f'Товар добавлен: {product.name} — {product.price} €')

        self.stdout.write(self.style.SUCCESS('Готово! Данные магазина на месте.'))
