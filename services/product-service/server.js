const express = require('express');
const { Pool } = require('pg');

const app = express();
const pool = new Pool({ connectionString: process.env.DATABASE_URL });

app.get('/health', (_, res) => res.json({ ok: true }));
app.get('/api/health', (_, res) => res.json({ ok: true, level: 7, stack: 'Microservices' }));

app.get('/api/products', async (_, res) => {
  try {
    const r = await pool.query(
      `SELECT p.id, p.name, p.slug, p.description, p.price, p.currency, p.sku,
              p.image, p.stock, p.is_featured, c.name AS category_name
       FROM products p LEFT JOIN categories c ON c.id = p.category_id
       WHERE p.is_active = true
       ORDER BY p.is_featured DESC, p.name`
    );
    res.json(r.rows);
  } catch (e) {
    res.status(500).json({ error: 'db_error', detail: String(e) });
  }
});

const port = process.env.PORT || 7001;
app.listen(port, () => console.log(`product-service on :${port}`));
