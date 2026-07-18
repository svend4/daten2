import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';

const API = import.meta.env.VITE_API_URL || '';

// axios с автоматическим Bearer-токеном
const authHeader = () => {
  const t = localStorage.getItem('token');
  return t ? { Authorization: `Bearer ${t}` } : {};
};

export default function App() {
  const [products, setProducts] = useState([]);
  const [cart, setCart] = useState([]);
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const total = useMemo(() => cart.reduce((s, it) => s + it.price * it.qty, 0), [cart]);

  // auth
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState('login'); // login | register
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authName, setAuthName] = useState('');
  const [myOrders, setMyOrders] = useState([]);

  useEffect(() => {
    axios.get(`${API}/api/products`).then(r => setProducts(r.data));
    if (localStorage.getItem('token')) {
      axios.get(`${API}/api/auth/me`, { headers: authHeader() })
        .then(r => { setUser(r.data); loadMyOrders(); })
        .catch(() => localStorage.removeItem('token'));
    }
  }, []);

  const loadMyOrders = () => {
    axios.get(`${API}/api/auth/orders`, { headers: authHeader() })
      .then(r => setMyOrders(r.data)).catch(() => setMyOrders([]));
  };

  const submitAuth = async () => {
    try {
      const url = authMode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const body = authMode === 'login'
        ? { email, password }
        : { email, password, name: authName };
      const r = await axios.post(`${API}${url}`, body);
      localStorage.setItem('token', r.data.token);
      setUser(r.data.user);
      setEmail(''); setPassword(''); setAuthName('');
      loadMyOrders();
    } catch (e) {
      alert(e.response?.data?.error || 'Ошибка авторизации');
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    setUser(null); setMyOrders([]);
  };

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
    const who = user ? user.name || user.email : name;
    if (!who || cart.length === 0) return;
    const payload = { name: who, phone, items: cart.map(x => ({ product_id: x.product_id, quantity: x.qty })) };
    const res = await axios.post(`${API}/api/orders`, payload, { headers: authHeader() });
    alert(`✅ Заказ принят! Номер для отслеживания: ${res.data.order_number}`);
    setCart([]); setName(''); setPhone('');
    if (user) loadMyOrders();
  };

  return (
    <div className="wrap">
      <h1>🌹 Магазин цветов</h1>
      <p className="muted">Уровень 5: React (Vite) + Flask API + SQLite</p>

      {/* --- авторизация --- */}
      <div className="cart" style={{ marginBottom: 16 }}>
        {user ? (
          <div className="row">
            <div className="grow">👤 Вход выполнен: <b>{user.name || user.email}</b></div>
            <button onClick={logout}>Выйти</button>
          </div>
        ) : (
          <>
            <div className="row">
              <button onClick={() => setAuthMode('login')} disabled={authMode === 'login'}>Вход</button>
              <button onClick={() => setAuthMode('register')} disabled={authMode === 'register'}>Регистрация</button>
            </div>
            {authMode === 'register' && (
              <input value={authName} onChange={e => setAuthName(e.target.value)} placeholder="Имя" />
            )}
            <input value={email} onChange={e => setEmail(e.target.value)} placeholder="Email" />
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Пароль (мин. 6)" />
            <button onClick={submitAuth}>{authMode === 'login' ? 'Войти' : 'Зарегистрироваться'}</button>
          </>
        )}
      </div>

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
            {!user && (
              <input value={name} onChange={e => setName(e.target.value)} placeholder="Ваше имя" />
            )}
            <input value={phone} onChange={e => setPhone(e.target.value)} placeholder="Телефон (необязательно)" />
            <button onClick={order} disabled={(!user && !name) || cart.length === 0}>Оформить заказ</button>
          </>
        )}
      </div>

      {/* --- история заказов (только для авторизованных) --- */}
      {user && (
        <div className="cart">
          <h2>📦 Мои заказы</h2>
          {myOrders.length === 0 ? <p className="muted">Пока нет заказов.</p> : myOrders.map(o => (
            <div className="row" key={o.order_number}>
              <div className="grow">№ {o.order_number.slice(0, 10)}… · {o.status} · {o.payment_status}</div>
              <div>{Number(o.total_amount).toFixed(2)} €</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
