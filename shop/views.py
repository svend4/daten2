# shop/views.py
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages

from .models import Product, Customer, Order, OrderItem


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
        customer = Customer.objects.create(
            name=name,
            phone=phone,
            address='—',
        )
        order = Order.objects.create(
            customer=customer,
            total_amount=Decimal(product.price),
            delivery_address='—',
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=1,
            price=product.price,
        )
        product.stock -= 1
        product.save()

        messages.success(request, f'Заказ #{order.id} на «{product.name}» оформлен!')
    except Exception:
        messages.error(request, 'Не удалось оформить заказ. Попробуйте позже.')

    return redirect('index')
