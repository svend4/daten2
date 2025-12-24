// src/utils/helpers.js

const helpers = {
    // Форматирование цены
    formatPrice(price) {
        return new Intl.NumberFormat('ru-RU', {
            style: 'currency',
            currency: 'RUB',
            minimumFractionDigits: 2
        }).format(price);
    },

    // Форматирование даты
    formatDate(date) {
        return new Intl.DateTimeFormat('ru-RU', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        }).format(new Date(date));
    },

    // Обрезка текста
    truncate(text, length = 100) {
        if (!text || text.length <= length) return text;
        return text.substring(0, length) + '...';
    },

    // Статус товара
    getStockStatus(stock) {
        if (stock > 10) {
            return { text: 'В наличии', class: 'success' };
        } else if (stock > 0) {
            return { text: `Осталось ${stock} шт.`, class: 'warning' };
        } else {
            return { text: 'Нет в наличии', class: 'danger' };
        }
    },

    // Статус заказа
    getOrderStatus(status) {
        const statuses = {
            new: { text: 'Новый', class: 'warning' },
            confirmed: { text: 'Подтверждён', class: 'info' },
            preparing: { text: 'Готовится', class: 'primary' },
            delivering: { text: 'Доставляется', class: 'secondary' },
            completed: { text: 'Завершён', class: 'success' },
            cancelled: { text: 'Отменён', class: 'danger' }
        };
        return statuses[status] || statuses.new;
    }
};

// Экспорт для использования в EJS
module.exports = helpers;
