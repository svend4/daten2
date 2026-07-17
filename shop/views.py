# shop/views.py
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages

from .models import Product, Customer, Order, OrderItem, OrderStatusHistory


def index(request):
    """Каталог товаров с необязательным поиском."""
    products = Product.objects.filter(is_active=True).select_related('category')

    search_query = request.GET.get('search', '').strip()
    if search_query:
        products = products.filter(name__icontains=search_query)

    return render(request, 'index.html', {
        'products': products,
        'search_query': search_query,
    })


def create_order(request, product_id):
    """Быстрый заказ одного товара по имени и телефону."""
    product = get_object_or_404(Product, id=product_id, is_active=True)

    if request.method != 'POST':
        return redirect('index')

    name = (request.POST.get('name') or '').strip()
    phone = (request.POST.get('phone') or '').strip()

    if not name:
        messages.error(request, 'Укажите имя')
        return redirect('index')

    if product.stock < 1:
        messages.error(request, f'Товар «{product.name}» закончился')
        return redirect('index')

    try:
        line_total = Decimal(product.price)
        customer = Customer.objects.create(name=name, phone=phone)
        order = Order.objects.create(
            customer=customer,
            subtotal=line_total,
            total_amount=line_total,
            payment_status='pending',
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            quantity=1,
            unit_price=product.price,
            line_total=line_total,
        )
        OrderStatusHistory.objects.create(order=order, status='new', note='Заказ создан')
        product.stock -= 1
        product.save()

        messages.success(
            request,
            f'Заказ на «{product.name}» оформлен! Номер для отслеживания: {order.order_number}'
        )
    except Exception:
        messages.error(request, 'Не удалось оформить заказ. Попробуйте позже.')

    return redirect('index')
