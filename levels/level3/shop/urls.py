# shop/urls.py
from django.urls import path

from . import views

app_name = 'shop'

urlpatterns = [
    # Каталог
    path('', views.ProductListView.as_view(), name='index'),
    path('category/<slug:slug>/', views.CategoryProductListView.as_view(), name='category'),
    path('product/<slug:slug>/', views.ProductDetailView.as_view(), name='product_detail'),

    # Корзина (хранится в сессии)
    path('cart/', views.cart_view, name='cart'),
    path('cart/add/<slug:slug>/', views.add_to_cart, name='add_to_cart'),
    path('cart/update/<slug:slug>/', views.update_cart, name='update_cart'),
    path('cart/remove/<slug:slug>/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/clear/', views.clear_cart, name='clear_cart'),

    # Оформление заказа
    path('checkout/', views.checkout, name='checkout'),
    path('order/<int:pk>/', views.order_success, name='order_success'),
    # Order.get_absolute_url() ссылается на shop:order_detail — та же страница заказа
    path('order/<int:pk>/detail/', views.order_success, name='order_detail'),
]
