const express = require('express');
const { Pool } = require('pg');

const app = express();
const pool = new Pool({ connectionString: process.env.DATABASE_URL });

app.get('/health', (_, res) => res.json({ ok: true }));

app.get('/api/products', async (_, res) => {
  try {
    const r = await pool.query('SELECT id, name, description, price, image, stock FROM products WHERE is_active = true ORDER BY id DESC');
    res.json(r.rows);
  } catch (e) {
    res.status(500).json({ error: 'db_error', detail: String(e) });
  }
});

const port = process.env.PORT || 7001;
app.listen(port, () => console.log(`product-service on :${port}`));
