import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';

const API = import.meta.env.VITE_API_URL || '';

export default function App() {
  const [products, setProducts] = useState([]);
  const [cart, setCart] = useState([]);
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const total = useMemo(() => cart.reduce((s, it) => s + it.price * it.qty, 0), [cart]);

  useEffect(() => {
    axios.get(`${API}/api/products`).then(r => setProducts(r.data));
  }, []);

  const add = (p) => {
    setCart(prev => {
      const found = prev.find(x => x.product_id === p.id);
      if (found) return prev.map(x => x.product_id === p.id ? { ...x, qty: x.qty + 1 } : x);
      return [...prev, { product_id: p.id, name: p.name, price: Number(p.price), qty: 1 }];
    });
  };

  const dec = (pid) => {
    setCart(prev => prev.map(x => x.product_id === pid ? { ...x, qty: x.qty - 1 } : x).filter(x => x.qty > 0));
  };

  const order = async () => {
    if (!name || cart.length === 0) return;
    const payload = { name, phone, items: cart.map(x => ({ product_id: x.product_id, quantity: x.qty })) };
    const res = await axios.post(`${API}/api/orders`, payload);
    alert(`✅ Заказ принят! Номер для отслеживания: ${res.data.order_number}`);
    setCart([]);
    setName('');
    setPhone('');
  };

  return (
    <div className="wrap">
      <h1>🌹 Магазин цветов</h1>
      <p className="muted">Уровень 5: React (Vite) + Flask API + SQLite</p>

      <div className="grid">
        {products.map(p => (
          <div className="card" key={p.id}>
            <div className="title">{p.name}</div>
            <div className="desc">{p.description}</div>
            <div className="price">{Number(p.price).toFixed(2)} €</div>
            <button onClick={() => add(p)}>Добавить в корзину</button>
          </div>
        ))}
      </div>

      <div className="cart">
        <h2>🧺 Корзина</h2>
        {cart.length === 0 ? <p className="muted">Пока пусто.</p> : (
          <>
            {cart.map(it => (
              <div className="row" key={it.product_id}>
                <div className="grow">{it.name} × {it.qty}</div>
                <div>{(it.price * it.qty).toFixed(2)} €</div>
                <button onClick={() => dec(it.product_id)}>-</button>
              </div>
            ))}
            <div className="row total">
              <div className="grow">Итого</div>
              <div>{total.toFixed(2)} €</div>
            </div>

            <input value={name} onChange={e => setName(e.target.value)} placeholder="Ваше имя" />
            <input value={phone} onChange={e => setPhone(e.target.value)} placeholder="Телефон (необязательно)" />
            <button onClick={order} disabled={!name || cart.length === 0}>Оформить заказ</button>
          </>
        )}
      </div>
    </div>
  );
}
