// registry.js — реестр 7 уровней-магазинов.
// Каждый уровень реализует единый контракт (openapi.yaml): /api/health,
// /api/products, /api/orders, /api/orders/<token>. URL переопределяются через env.
const LEVELS = [
  { level: 1, stack: 'PHP',           url: process.env.LEVEL1_URL || 'http://localhost:8001' },
  { level: 2, stack: 'Flask',         url: process.env.LEVEL2_URL || 'http://localhost:8002' },
  { level: 3, stack: 'Django',        url: process.env.LEVEL3_URL || 'http://localhost:8003' },
  { level: 4, stack: 'Express',       url: process.env.LEVEL4_URL || 'http://localhost:8004' },
  { level: 5, stack: 'React+Flask',   url: process.env.LEVEL5_URL || 'http://localhost:8005' },
  { level: 6, stack: 'Next.js',       url: process.env.LEVEL6_URL || 'http://localhost:8006' },
  { level: 7, stack: 'Microservices', url: process.env.LEVEL7_URL || 'http://localhost:8007' },
];

module.exports = { LEVELS };
