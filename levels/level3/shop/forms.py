# shop/forms.py
from django import forms


class AddToCartForm(forms.Form):
    """Форма добавления товара в корзину"""
    quantity = forms.IntegerField(
        label='Количество',
        min_value=1,
        max_value=99,
        initial=1,
        widget=forms.NumberInput(attrs={'min': 1, 'max': 99}),
    )


class CheckoutForm(forms.Form):
    """Форма оформления заказа"""
    name = forms.CharField(
        label='Ваше имя',
        max_length=200,
        widget=forms.TextInput(attrs={'placeholder': 'Иван Иванов'}),
    )
    phone = forms.CharField(
        label='Телефон',
        max_length=20,
        widget=forms.TextInput(attrs={'placeholder': '+7 900 000-00-00'}),
    )
    email = forms.EmailField(
        label='Email',
        required=False,
        widget=forms.EmailInput(attrs={'placeholder': 'mail@example.com'}),
    )
    address = forms.CharField(
        label='Адрес доставки',
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Город, улица, дом, квартира'}),
    )
    notes = forms.CharField(
        label='Примечания',
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Пожелания к заказу'}),
    )
