// policy.js — политика файрвола: пороги риска, лимиты вызовов инструментов,
// белый список инструментов и запрещённые поля. Переопределяется через env.
module.exports = {
  // пороги суммарного риска (0..100)
  thresholds: {
    flag: Number(process.env.FW_FLAG || 25),   // >= flag → пометить/санитизировать
    block: Number(process.env.FW_BLOCK || 50),  // >= block → заблокировать
  },
  // разрешённые инструменты и лимиты аргументов create_order
  tools: {
    allowed: ['list_products', 'get_order', 'create_order'],
    create_order: {
      maxQtyPerItem: Number(process.env.FW_MAX_QTY || 100),
      maxItems: Number(process.env.FW_MAX_ITEMS || 20),
      maxUnits: Number(process.env.FW_MAX_UNITS || 300),
      maxNameLen: 80,
      // клиент НЕ должен задавать эти поля — их считает сервер
      forbiddenKeys: ['price', 'unit_price', 'discount', 'total', 'total_amount', 'status', 'payment_status'],
    },
  },
};
