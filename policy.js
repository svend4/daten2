// policy.js — политика автономии: что можно делать самому, а что — только с
// одобрения человека. Всё настраивается через env и /api/config.
module.exports = {
  dryRun: process.env.AUTO_DRY_RUN !== 'false',        // по умолчанию — сухой прогон (безопасно)
  autoThreshold: Number(process.env.AUTO_THRESHOLD || 30), // impact <= порога → авто; иначе к человеку
  maxActionsPerCycle: Number(process.env.MAX_ACTIONS || 5), // предохранитель от лавины
  cooldownCycles: Number(process.env.COOLDOWN || 3),        // не трогать один товар N циклов подряд
  reorderBudget: Number(process.env.REORDER_BUDGET || 200), // масштаб «дорогого» дозаказа (€)
  // какие типы действий вообще включены
  enabled: {
    reorder: process.env.EN_REORDER !== 'false',
    price_change: process.env.EN_PRICE !== 'false',
    flag: process.env.EN_FLAG !== 'false',
  },
};
