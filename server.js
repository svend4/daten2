// server.js
const { initDb } = require('./init_db');

const PORT = process.env.PORT || 3000;
const HOST = process.env.HOST || '0.0.0.0';

// Сначала гарантируем схему и сид (идемпотентно), затем стартуем
initDb()
    .then(() => {
        const app = require('./app');
        app.listen(PORT, HOST, () => {
            console.log(`
╔════════════════════════════════════════╗
║   🌹 Магазин цветов - Node.js + Express   ║
╚════════════════════════════════════════╝

🚀 Сервер запущен:
   http://localhost:${PORT}

📊 Окружение: ${process.env.NODE_ENV || 'development'}
⏰ Время запуска: ${new Date().toLocaleString('ru-RU')}

Нажмите Ctrl+C для остановки
    `);
        });
    })
    .catch((err) => {
        console.error('❌ Не удалось инициализировать БД:', err);
        process.exit(1);
    });

// Обработка сигналов завершения
process.on('SIGINT', () => {
    console.log('\n👋 Остановка сервера...');
    process.exit(0);
});

process.on('SIGTERM', () => {
    console.log('\n👋 Остановка сервера...');
    process.exit(0);
});

// Обработка необработанных ошибок
process.on('unhandledRejection', (err) => {
    console.error('❌ Необработанная ошибка Promise:', err);
    process.exit(1);
});

process.on('uncaughtException', (err) => {
    console.error('❌ Необработанное исключение:', err);
    process.exit(1);
});
