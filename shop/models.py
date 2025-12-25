# shop/models.py
from django.db import models
from django.urls import reverse
from django.core.validators import MinValueValidator

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
    
    def get_absolute_url(self):
        return reverse('shop:category', kwargs={'slug': self.slug})


class Product(models.Model):
    """Товар"""
    name = models.CharField('Название', max_length=200)
    slug = models.SlugField('URL', max_length=200, unique=True)
    description = models.TextField('Описание', blank=True)
    price = models.DecimalField(
        'Цена', 
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name='Категория'
    )
    image = models.ImageField(
        'Изображение',
        upload_to='products/',
        blank=True,
        null=True
    )
    stock = models.PositiveIntegerField(
        'Количество на складе',
        default=0,
        validators=[MinValueValidator(0)]
    )
    is_active = models.BooleanField('Активен', default=True)
    created_at = models.DateTimeField('Дата создания', auto_now_add=True)
    updated_at = models.DateTimeField('Дата обновления', auto_now=True)
    
    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
            models.Index(fields=['category']),
        ]
    
    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse('shop:product_detail', kwargs={'slug': self.slug})
    
    @property
    def is_in_stock(self):
        """Проверка наличия на складе"""
        return self.stock > 0
    
    @property
    def stock_status(self):
        """Статус наличия"""
        if self.stock > 10:
            return 'В наличии'
        elif self.stock > 0:
            return f'Осталось {self.stock} шт.'
        else:
            return 'Нет в наличии'


class Customer(models.Model):
    """Клиент"""
    name = models.CharField('Имя', max_length=200)
    phone = models.CharField('Телефон', max_length=20)
    email = models.EmailField('Email', blank=True)
    address = models.TextField('Адрес')
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
    
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='orders',
        verbose_name='Клиент'
    )
    total_amount = models.DecimalField(
        'Общая сумма',
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    status = models.CharField(
        'Статус',
        max_length=20,
        choices=STATUS_CHOICES,
        default='new'
    )
    delivery_address = models.TextField('Адрес доставки')
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
    
    def get_absolute_url(self):
        return reverse('shop:order_detail', kwargs={'pk': self.pk})


class OrderItem(models.Model):
    """Товар в заказе"""
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Заказ'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name='Товар'
    )
    quantity = models.PositiveIntegerField(
        'Количество',
        validators=[MinValueValidator(1)]
    )
    price = models.DecimalField(
        'Цена на момент заказа',
        max_digits=10,
        decimal_places=2
    )
    
    class Meta:
        verbose_name = 'Товар в заказе'
        verbose_name_plural = 'Товары в заказе'
    
    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
    
    @property
    def subtotal(self):
        """Подытог"""
        return self.price * self.quantity
