# shop/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import Category, Product, Customer, Order, OrderItem


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Админка категорий"""
    list_display = ['name', 'slug', 'created_at']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']
    ordering = ['name']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Админка товаров"""
    list_display = [
        'name', 'category', 'price', 'stock',
        'is_active', 'image_preview', 'created_at'
    ]
    list_filter = ['is_active', 'category', 'created_at']
    list_editable = ['price', 'stock', 'is_active']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['-created_at']
    readonly_fields = ['image_preview', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'slug', 'category', 'description')
        }),
        ('Цена и наличие', {
            'fields': ('price', 'stock', 'is_active')
        }),
        ('Изображение', {
            'fields': ('image', 'image_preview')
        }),
        ('Даты', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def image_preview(self, obj):
        """Превью изображения (image — путь или URL)"""
        if obj.image:
            src = obj.image if obj.image.startswith('http') else '/static/' + obj.image
            return format_html(
                '<img src="{}" style="max-height: 100px; max-width: 100px;" />',
                src
            )
        return '-'
    image_preview.short_description = 'Превью'


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """Админка клиентов"""
    list_display = ['name', 'phone', 'email', 'orders_count', 'created_at']
    search_fields = ['name', 'phone', 'email']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    
    def orders_count(self, obj):
        """Количество заказов"""
        return obj.orders.count()
    orders_count.short_description = 'Заказов'


class OrderItemInline(admin.TabularInline):
    """Inline для товаров в заказе"""
    model = OrderItem
    extra = 0
    readonly_fields = ['product', 'quantity', 'price', 'subtotal']
    can_delete = False
    
    def subtotal(self, obj):
        return obj.subtotal


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Админка заказов"""
    list_display = [
        'id', 'customer', 'total_amount',
        'status_badge', 'created_at'
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['id', 'customer__name', 'customer__phone']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at', 'total_amount']
    inlines = [OrderItemInline]
    
    fieldsets = (
        ('Клиент', {
            'fields': ('customer',)
        }),
        ('Заказ', {
            'fields': ('status', 'total_amount', 'delivery_address', 'notes')
        }),
        ('Даты', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def status_badge(self, obj):
        """Цветной статус"""
        colors = {
            'new': '#ffc107',
            'confirmed': '#17a2b8',
            'preparing': '#007bff',
            'delivering': '#6f42c1',
            'completed': '#28a745',
            'cancelled': '#dc3545',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background: {}; color: white; padding: 5px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Статус'


# Настройка админ-панели
admin.site.site_header = '🌹 Магазин цветов - Администрирование'
admin.site.site_title = 'Магазин цветов'
admin.site.index_title = 'Управление магазином'
