# shop/models.py
import uuid

from django.db import models
from django.core.validators import MinValueValidator


def generate_order_number():
    return uuid.uuid4().hex


# =====================================================================
# ЯРУС 1 — ПОСТОЯННЫЙ (durable)
# =====================================================================

class Category(models.Model):
    """Категория товаров"""
    name = models.CharField('Название', max_length=200, unique=True)
    description = models.TextField('Описание', blank=True)
    slug = models.SlugField('URL', max_length=200, unique=True)
    created_at = models.DateTimeField('Дата создания', auto_now_add=True)

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    """Товар"""
    name = models.CharField('Название', max_length=200)
    slug = models.SlugField('URL', max_length=200, unique=True)
    description = models.TextField('Описание', blank=True)
    price = models.DecimalField('Цена', max_digits=10, decimal_places=2,
                                validators=[MinValueValidator(0)])
    currency = models.CharField('Валюта', max_length=3, default='EUR')
    sku = models.CharField('Артикул', max_length=64, blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE,
                                 related_name='products', verbose_name='Категория')
    image = models.CharField('Изображение (путь или URL)', max_length=500, blank=True)
    stock = models.PositiveIntegerField('Количество на складе', default=0,
                                        validators=[MinValueValidator(0)])
    is_active = models.BooleanField('Активен', default=True)
    is_featured = models.BooleanField('Рекомендуемый', default=False)
    created_at = models.DateTimeField('Дата создания', auto_now_add=True)
    updated_at = models.DateTimeField('Дата обновления', auto_now=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['-is_featured', 'name']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return self.name

    @property
    def is_in_stock(self):
        return self.stock > 0

    @property
    def stock_status(self):
        if self.stock > 10:
            return 'В наличии'
        elif self.stock > 0:
            return f'Осталось {self.stock} шт.'
        return 'Нет в наличии'


class Customer(models.Model):
    """Клиент"""
    name = models.CharField('Имя', max_length=200)
    phone = models.CharField('Телефон', max_length=20)
    email = models.EmailField('Email', blank=True)
    address = models.TextField('Адрес', blank=True)
    city = models.CharField('Город', max_length=120, blank=True)
    postal_code = models.CharField('Индекс', max_length=20, blank=True)
    notes = models.TextField('Примечания', blank=True)
    created_at = models.DateTimeField('Дата регистрации', auto_now_add=True)

    class Meta:
        verbose_name = 'Клиент'
        verbose_name_plural = 'Клиенты'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Order(models.Model):
    """Заказ"""
    STATUS_CHOICES = [
        ('new', 'Новый'),
        ('confirmed', 'Подтверждён'),
        ('preparing', 'Готовится'),
        ('delivering', 'Доставляется'),
        ('completed', 'Завершён'),
        ('cancelled', 'Отменён'),
    ]
    PAYMENT_CHOICES = [
        ('pending', 'Ожидает оплаты'),
        ('paid', 'Оплачен'),
        ('refunded', 'Возврат'),
        ('failed', 'Ошибка оплаты'),
    ]

    order_number = models.CharField('Номер заказа', max_length=32, unique=True,
                                    default=generate_order_number, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE,
                                 related_name='orders', verbose_name='Клиент')
    subtotal = models.DecimalField('Сумма позиций', max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField('Скидка', max_digits=10, decimal_places=2, default=0)
    delivery_fee = models.DecimalField('Доставка', max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField('Общая сумма', max_digits=10, decimal_places=2,
                                       validators=[MinValueValidator(0)])
    currency = models.CharField('Валюта', max_length=3, default='EUR')
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='new')
    payment_status = models.CharField('Оплата', max_length=20, choices=PAYMENT_CHOICES, default='pending')
    delivery_address = models.TextField('Адрес доставки', blank=True)
    delivery_date = models.DateField('Дата доставки', null=True, blank=True)
    notes = models.TextField('Примечания', blank=True)
    created_at = models.DateTimeField('Дата создания', auto_now_add=True)
    updated_at = models.DateTimeField('Дата обновления', auto_now=True)

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Заказ #{self.id} - {self.customer.name}"


class OrderItem(models.Model):
    """Позиция заказа (со снимком названия и цены)"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE,
                              related_name='items', verbose_name='Заказ')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True,
                                verbose_name='Товар')
    product_name = models.CharField('Название (снимок)', max_length=200, default='')
    quantity = models.PositiveIntegerField('Количество', validators=[MinValueValidator(1)])
    unit_price = models.DecimalField('Цена за единицу', max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField('Сумма позиции', max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Товар в заказе'
        verbose_name_plural = 'Товары в заказе'

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"

    @property
    def subtotal(self):
        return self.line_total


class OrderStatusHistory(models.Model):
    """История смены статусов заказа (аудит)"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE,
                              related_name='status_history', verbose_name='Заказ')
    status = models.CharField('Статус', max_length=20)
    note = models.CharField('Примечание', max_length=255, blank=True)
    changed_at = models.DateTimeField('Когда', auto_now_add=True)

    class Meta:
        verbose_name = 'Смена статуса'
        verbose_name_plural = 'История статусов'
        ordering = ['changed_at']

    def __str__(self):
        return f"#{self.order_id}: {self.status}"


# =====================================================================
# ЯРУС 2 — ВРЕМЕННЫЙ / КЭШ (temporal): доступен, но демо-поток
# использует сессионную корзину Django (выбор уровня).
# =====================================================================

class Cart(models.Model):
    session_id = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Корзина (кэш)'
        verbose_name_plural = 'Корзины (кэш)'


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)


class ProductViewStats(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='view_stats')
    views = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField(auto_now_add=True)
