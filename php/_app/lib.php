<?php
// Общие функции приема заявок a-gavrish.com для обычного хостинга (PHP + SQLite).
declare(strict_types=1);

const CONSENT_VERSION = '2026-11-03';
const RETENTION_DAYS = 3 * 365;
const STATUSES = ['new' => 'Новая', 'work' => 'В работе', 'closed' => 'Закрыта'];

function data_dir(): string {
    $d = dirname(__DIR__) . '/_data';
    if (!is_dir($d)) { mkdir($d, 0700, true); }
    if (!file_exists("$d/.htaccess")) { file_put_contents("$d/.htaccess", "Require all denied\nDeny from all\n"); }
    if (!file_exists("$d/index.php")) { file_put_contents("$d/index.php", "<?php http_response_code(404);"); }
    return $d;
}

function settings(): array {
    $f = data_dir() . '/settings.json';
    return file_exists($f) ? (json_decode((string)file_get_contents($f), true) ?: []) : [];
}

function save_settings(array $s): void {
    $f = data_dir() . '/settings.json';
    file_put_contents($f, json_encode($s, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT), LOCK_EX);
    @chmod($f, 0600);
}

function db(): PDO {
    static $pdo = null;
    if ($pdo) return $pdo;
    $pdo = new PDO('sqlite:' . data_dir() . '/leads.sqlite3', null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC]);
    $pdo->exec("CREATE TABLE IF NOT EXISTS leads(
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        name TEXT NOT NULL, contact TEXT NOT NULL, pain TEXT, country TEXT,
        consent_pd INTEGER NOT NULL, consent_ads INTEGER NOT NULL, consent_version TEXT NOT NULL,
        ip TEXT, user_agent TEXT, page TEXT, status TEXT NOT NULL DEFAULT 'new')");
    $pdo->exec("CREATE INDEX IF NOT EXISTS ix_leads_ip_time ON leads(ip, created_at)");
    // удаление заявок старше срока хранения, не чаще раза в сутки
    $s = settings();
    if (($s['purged'] ?? '') !== gmdate('Y-m-d')) {
        $border = gmdate('Y-m-d\TH:i:s\Z', time() - RETENTION_DAYS * 86400);
        $pdo->prepare("DELETE FROM leads WHERE updated_at < ?")->execute([$border]);
        $s['purged'] = gmdate('Y-m-d');
        save_settings($s);
    }
    return $pdo;
}

function now(): string { return gmdate('Y-m-d\TH:i:s\Z'); }
function e(?string $s): string { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }
function client_ip(): string { return (string)($_SERVER['HTTP_X_REAL_IP'] ?? $_SERVER['REMOTE_ADDR'] ?? ''); }

function notify(int $id): void {
    $s = settings();
    if (empty($s['tg_token']) || empty($s['tg_chat'])) return;
    $host = $_SERVER['HTTP_HOST'] ?? 'a-gavrish.com';
    $text = "Новая заявка №$id. Открыть: https://$host/admin/";
    $ctx = stream_context_create(['http' => ['method' => 'POST', 'timeout' => 8,
        'header' => "Content-Type: application/x-www-form-urlencoded\r\n",
        'content' => http_build_query(['chat_id' => $s['tg_chat'], 'text' => $text, 'disable_web_page_preview' => 'true'])]]);
    @file_get_contents('https://api.telegram.org/bot' . $s['tg_token'] . '/sendMessage', false, $ctx);
}
