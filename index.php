<?php
// index.php - ВЕСЬ САЙТ В ОДНОМ ФАЙЛЕ!

// Подключение к базе данных
$db = new SQLite3('flowers.db');

// Переменные для сообщений
$success_message = '';
$error_message = '';

// ========== ОБРАБОТКА ФОРМЫ ЗАКАЗА ==========
if ($_SERVER['REQUEST_METHOD'] == 'POST' && isset($_POST['action']) && $_POST['action'] == 'order') {
    
    $name = $_POST['name'];
    $phone = $_POST['phone'];
    $email = $_POST['email'];
    $address = $_POST['address'];
    $product_id = $_POST['product_id'];
    $quantity = $_POST['quantity'];
    
    // Получить цену товара
    $stmt = $db->prepare('SELECT price, stock FROM products WHERE id = ?');
    $stmt->bindValue(1, $product_id, SQLITE3_INTEGER);
    $result = $stmt->execute();
    $product = $result->fetchArray(SQLITE3_ASSOC);
    
    if ($product && $quantity > 0 && $product['stock'] >= $quantity) {
        $total = $product['price'] * $quantity;

        // Начать транзакцию
        $db->exec('BEGIN');

        try {
            // Создать заказ (схема БД: orders хранит имя и телефон напрямую)
            $stmt = $db->prepare('INSERT INTO orders (customer_name, phone, status) VALUES (?, ?, "new")');
            $stmt->bindValue(1, $name, SQLITE3_TEXT);
            $stmt->bindValue(2, $phone, SQLITE3_TEXT);
            $stmt->execute();
            $order_id = $db->lastInsertRowID();

            // Добавить товар в заказ (колонка qty согласно схеме)
            $stmt = $db->prepare('INSERT INTO order_items (order_id, product_id, qty, price) VALUES (?, ?, ?, ?)');
            $stmt->bindValue(1, $order_id, SQLITE3_INTEGER);
            $stmt->bindValue(2, $product_id, SQLITE3_INTEGER);
            $stmt->bindValue(3, $quantity, SQLITE3_INTEGER);
            $stmt->bindValue(4, $product['price'], SQLITE3_FLOAT);
            $stmt->execute();

            // Уменьшить остаток на складе
            $stmt = $db->prepare('UPDATE products SET stock = stock - ? WHERE id = ?');
            $stmt->bindValue(1, $quantity, SQLITE3_INTEGER);
            $stmt->bindValue(2, $product_id, SQLITE3_INTEGER);
            $stmt->execute();

            $db->exec('COMMIT');

            $success_message = "✅ Заказ #$order_id успешно оформлен! Сумма: $total руб. Мы свяжемся с вами по телефону " . htmlspecialchars($phone);

        } catch (Exception $e) {
            $db->exec('ROLLBACK');
            error_log('Order creation failed: ' . $e->getMessage());
            $error_message = "❌ Не удалось оформить заказ. Попробуйте позже.";
        }

    } else {
        $error_message = "❌ Извините, товара нет в наличии или недостаточное количество";
    }
}

// ========== ПОЛУЧИТЬ ВСЕ ТОВАРЫ ==========
$result = $db->query('
    SELECT p.*, c.name as category_name 
    FROM products p
    LEFT JOIN categories c ON p.category_id = c.id
    WHERE p.is_active = 1
    ORDER BY c.name, p.name
');

$products = [];
while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
    $products[] = $row;
}

// ========== ПОИСК ТОВАРОВ ==========
$search_query = '';
$search_results = [];
if (isset($_GET['search']) && !empty($_GET['search'])) {
    $search_query = $_GET['search'];
    $stmt = $db->prepare('SELECT * FROM products WHERE name LIKE ? AND is_active = 1');
    $stmt->bindValue(1, '%' . $search_query . '%', SQLITE3_TEXT);
    $result = $stmt->execute();
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        $search_results[] = $row;
    }
}

?>

<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🌹 Магазин цветов - Доставка цветов</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #ffeef8 0%, #fff5f7 100%);
            padding: 20px;
            line-height: 1.6;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 5px 25px rgba(0,0,0,0.1);
        }
        
        header {
            text-align: center;
            margin-bottom: 40px;
            padding-bottom: 20px;
            border-bottom: 3px solid #ff69b4;
        }
        
        h1 {
            color: #d63384;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: #666;
            font-size: 1.1em;
        }
        
        /* Поиск */
        .search-box {
            margin: 30px 0;
            text-align: center;
        }
        
        .search-box input {
            padding: 12px 20px;
            width: 60%;
            border: 2px solid #ff69b4;
            border-radius: 25px;
            font-size: 16px;
        }
        
        .search-box button {
            padding: 12px 30px;
            background: #d63384;
            color: white;
            border: none;
            border-radius: 25px;
            cursor: pointer;
            font-size: 16px;
            margin-left: 10px;
        }
        
        .search-box button:hover {
            background: #c22370;
        }
        
        /* Сообщения */
        .message {
            padding: 15px;
            margin: 20px 0;
            border-radius: 8px;
            font-weight: bold;
        }
        
        .success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        /* Сетка товаров */
        .products-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 30px;
            margin: 30px 0;
        }
        
        .product-card {
            background: white;
            border: 2px solid #ffc0cb;
            border-radius: 12px;
            padding: 20px;
            transition: all 0.3s ease;
            position: relative;
        }
        
        .product-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px rgba(214, 51, 132, 0.2);
        }
        
        .product-card img {
            width: 100%;
            height: 220px;
            object-fit: cover;
            border-radius: 8px;
            margin-bottom: 15px;
        }
        
        .category-badge {
            position: absolute;
            top: 30px;
            right: 30px;
            background: #d63384;
            color: white;
            padding: 5px 12px;
            border-radius: 15px;
            font-size: 12px;
        }
        
        .product-card h3 {
            color: #333;
            margin-bottom: 10px;
            font-size: 1.3em;
        }
        
        .product-card p {
            color: #666;
            margin-bottom: 15px;
            font-size: 0.95em;
        }
        
        .price {
            font-size: 1.5em;
            color: #28a745;
            font-weight: bold;
            margin-bottom: 10px;
        }
        
        .stock {
            color: #666;
            font-size: 0.9em;
            margin-bottom: 15px;
        }
        
        /* Форма заказа */
        .order-form {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin-top: 15px;
        }
        
        .order-form input,
        .order-form textarea {
            width: 100%;
            padding: 10px;
            margin: 8px 0;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
        }
        
        .order-form button {
            width: 100%;
            padding: 12px;
            background: #28a745;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            font-weight: bold;
            margin-top: 10px;
        }
        
        .order-form button:hover {
            background: #218838;
        }
        
        .toggle-form {
            background: #d63384;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            width: 100%;
        }
        
        .toggle-form:hover {
            background: #c22370;
        }
        
        /* Скрыть форму по умолчанию */
        .order-form {
            display: none;
        }
        
        footer {
            text-align: center;
            margin-top: 50px;
            padding-top: 30px;
            border-top: 2px solid #ffc0cb;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🌹 Магазин цветов</h1>
            <p class="subtitle">Свежие цветы с доставкой по городу</p>
        </header>
        
        <!-- Поиск -->
        <div class="search-box">
            <form method="GET" style="display: inline;">
                <input type="text" name="search" placeholder="Поиск цветов..." value="<?= htmlspecialchars($search_query) ?>">
                <button type="submit">🔍 Найти</button>
            </form>
            <?php if ($search_query): ?>
                <a href="index.php" style="margin-left: 10px; color: #d63384;">✖ Сбросить</a>
            <?php endif; ?>
        </div>
        
        <!-- Сообщения -->
        <?php if ($success_message): ?>
            <div class="message success"><?= $success_message ?></div>
        <?php endif; ?>
        
        <?php if ($error_message): ?>
            <div class="message error"><?= $error_message ?></div>
        <?php endif; ?>
        
        <!-- Результаты поиска -->
        <?php if ($search_query && count($search_results) > 0): ?>
            <h2 style="margin: 30px 0;">Результаты поиска "<?= htmlspecialchars($search_query) ?>" (<?= count($search_results) ?>)</h2>
            <?php $products = $search_results; ?>
        <?php elseif ($search_query): ?>
            <div class="message error">По запросу "<?= htmlspecialchars($search_query) ?>" ничего не найдено</div>
        <?php endif; ?>
        
        <!-- Каталог товаров -->
        <div class="products-grid">
            <?php foreach ($products as $product): ?>
            <div class="product-card">
                <span class="category-badge"><?= htmlspecialchars($product['category_name']) ?></span>
                
                <?php if (!empty($product['image']) && file_exists($product['image'])): ?>
                    <img src="<?= htmlspecialchars($product['image']) ?>" alt="<?= htmlspecialchars($product['name']) ?>">
                <?php else: ?>
                    <img src="https://via.placeholder.com/280x220/ffc0cb/d63384?text=<?= urlencode($product['name']) ?>" alt="<?= htmlspecialchars($product['name']) ?>">
                <?php endif; ?>
                
                <h3><?= htmlspecialchars($product['name']) ?></h3>
                <p><?= htmlspecialchars($product['description']) ?></p>
                <div class="price"><?= number_format($product['price'], 2, ',', ' ') ?> ₽</div>
                <div class="stock">
                    <?php if ($product['stock'] > 10): ?>
                        ✅ В наличии (<?= $product['stock'] ?> шт.)
                    <?php elseif ($product['stock'] > 0): ?>
                        ⚠️ Осталось мало (<?= $product['stock'] ?> шт.)
                    <?php else: ?>
                        ❌ Нет в наличии
                    <?php endif; ?>
                </div>
                
                <?php if ($product['stock'] > 0): ?>
                <button class="toggle-form" onclick="toggleForm('form-<?= $product['id'] ?>')">
                    📝 Заказать
                </button>
                
                <div class="order-form" id="form-<?= $product['id'] ?>">
                    <form method="POST">
                        <input type="hidden" name="action" value="order">
                        <input type="hidden" name="product_id" value="<?= $product['id'] ?>">
                        
                        <input type="text" name="name" placeholder="Ваше имя *" required>
                        <input type="tel" name="phone" placeholder="Телефон * (например: +7-900-123-45-67)" required>
                        <input type="email" name="email" placeholder="Email (необязательно)">
                        <textarea name="address" rows="3" placeholder="Адрес доставки *" required></textarea>
                        
                        <label>Количество:</label>
                        <input type="number" name="quantity" value="1" min="1" max="<?= $product['stock'] ?>" required>
                        
                        <div style="margin: 15px 0; padding: 10px; background: white; border-radius: 5px;">
                            <strong>Итого: <span id="total-<?= $product['id'] ?>"><?= number_format($product['price'], 2, ',', ' ') ?></span> ₽</strong>
                        </div>
                        
                        <button type="submit">✅ Оформить заказ</button>
                    </form>
                </div>
                <?php else: ?>
                <button class="toggle-form" disabled style="background: #ccc; cursor: not-allowed;">
                    Нет в наличии
                </button>
                <?php endif; ?>
            </div>
            <?php endforeach; ?>
        </div>
        
        <?php if (count($products) == 0 && !$search_query): ?>
            <div class="message error">В каталоге пока нет товаров. Запустите init_db.php для добавления тестовых данных.</div>
        <?php endif; ?>
        
        <footer>
            <p>© 2024 Магазин цветов. Все права защищены.</p>
            <p>📞 Телефон: +7 (900) 123-45-67 | 📧 Email: info@flowers.ru</p>
        </footer>
    </div>
    
    <script>
        // Показать/скрыть форму заказа
        function toggleForm(formId) {
            const form = document.getElementById(formId);
            if (form.style.display === 'none' || form.style.display === '') {
                form.style.display = 'block';
            } else {
                form.style.display = 'none';
            }
        }
        
        // Автоматический расчет суммы
        document.querySelectorAll('input[name="quantity"]').forEach(input => {
            input.addEventListener('input', function() {
                const productId = this.closest('form').querySelector('input[name="product_id"]').value;
                const price = <?= json_encode(array_column($products, 'price', 'id')) ?>[productId];
                const quantity = this.value;
                const total = price * quantity;
                document.getElementById('total-' + productId).textContent = total.toFixed(2).replace('.', ',').replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
            });
        });
    </script>
</body>
</html>

<?php
$db->close();
?>