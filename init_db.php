<?php
// init_db.php — генерирует flowers.db из канонических schema.sql + seed.sql.
// Идемпотентно: schema — CREATE IF NOT EXISTS, seed — INSERT OR IGNORE.

function init_flower_db($dbPath = null) {
    $dbPath = $dbPath ?: (getenv('DATABASE_PATH') ?: __DIR__ . '/flowers.db');
    $db = new SQLite3($dbPath);
    $db->exec(file_get_contents(__DIR__ . '/schema.sql'));
    $db->exec(file_get_contents(__DIR__ . '/seed.sql'));
    $db->close();
    return $dbPath;
}

// Запуск из CLI: php init_db.php
if (PHP_SAPI === 'cli' && isset($argv[0]) && realpath($argv[0]) === realpath(__FILE__)) {
    echo 'БД готова: ' . init_flower_db() . "\n";
}
