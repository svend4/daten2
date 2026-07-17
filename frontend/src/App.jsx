import React, { useEffect, useState } from 'react';

export default function App() {
  const [products, setProducts] = useState([]);
  const [cart, setCart] = useState([]);

  useEffect(() => {
    fetch('/api/products').then(r => r.json()).then(setProducts);
  }, []);

  const add = (p) => setCart(prev => [...prev, { product_id: p.id, name: p.name, quantity: 1 }]);

  const order = async () => {
    const name = prompt('Ваше имя?') || '';
    if (!name || cart.length === 0) return;
    const r = await fetch('/api/orders', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name, items: cart }) });
    const data = await r.json();
    alert('✅ Заказ принят! Номер для отслеживания: ' + data.order_number);
    setCart([]);
  };

  return (
    <div style={{fontFamily:'Arial', maxWidth: 980, margin:'24px auto', padding:16}}>
      <h1>🌹 Enterprise Flower Shop</h1>
      <p style={{color:'#777'}}>Уровень 7: микросервисы + nginx gateway + Postgres + RabbitMQ</p>

      <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(240px,1fr))', gap:16}}>
        {products.map(p => (
          <div key={p.id} style={{border:'1px solid #e5e5e5', borderRadius:12, padding:12, background:'white'}}>
            <div style={{fontWeight:'bold'}}>{p.name}</div>
            <div style={{color:'#555', margin:'8px 0'}}>{p.description}</div>
            <div style={{fontWeight:'bold'}}>{Number(p.price).toFixed(2)} €</div>
            <button style={{marginTop:10, padding:10, width:'100%'}} onClick={() => add(p)}>Добавить</button>
          </div>
        ))}
      </div>

      <div style={{marginTop:24, border:'1px solid #e5e5e5', borderRadius:12, padding:12, background:'white'}}>
        <h2>🧺 Корзина</h2>
        <p>Товаров: {cart.length}</p>
        <button disabled={cart.length===0} onClick={order} style={{padding:10, width:'100%'}}>Оформить заказ</button>
      </div>
    </div>
  );
}
