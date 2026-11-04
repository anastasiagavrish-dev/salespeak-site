<?php
// Прием заявки с формы сайта.
declare(strict_types=1);
require dirname(__DIR__) . '/_app/lib.php';
header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');

function out(int $code, array $body): never { http_response_code($code); echo json_encode($body, JSON_UNESCAPED_UNICODE); exit; }

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') out(405, ['ok' => false, 'error' => 'Метод не поддерживается']);
$raw = file_get_contents('php://input', false, null, 0, 65536);
$d = json_decode((string)$raw, true);
if (!is_array($d)) out(400, ['ok' => false, 'error' => 'Не удалось прочитать заявку. Обновите страницу и попробуйте еще раз.']);
if (trim((string)($d['website'] ?? '')) !== '') out(200, ['ok' => true, 'id' => 0]); // honeypot

$name = mb_substr(trim((string)($d['name'] ?? '')), 0, 120);
$contact = mb_substr(trim((string)($d['contact'] ?? '')), 0, 120);
$pain = mb_substr(trim((string)($d['pain'] ?? '')), 0, 2000);
$country = mb_substr(trim((string)($d['country'] ?? '')), 0, 20);
$errors = [];
if ($name === '') $errors['name'] = 'Напишите, как к вам обращаться';
$digits = preg_replace('/\D/', '', $contact);
if (!(strlen($digits) >= 10 || preg_match('/^@?[A-Za-z0-9_]{5,32}$/', $contact))) $errors['contact'] = 'Нужен телефон, например +7 701 123 45 67, или ник в Telegram';
if (($d['consent_pd'] ?? null) !== true) $errors['consent_pd'] = 'Без согласия заявку отправить нельзя';
if ($errors) out(422, ['ok' => false, 'errors' => $errors]);

try {
    $pdo = db();
    $ip = client_ip();
    $st = $pdo->prepare("SELECT COUNT(*) FROM leads WHERE ip=? AND created_at>?");
    $st->execute([$ip, gmdate('Y-m-d\TH:i:s\Z', time() - 3600)]);
    if ((int)$st->fetchColumn() >= 5) out(429, ['ok' => false, 'error' => 'Слишком много заявок с вашего адреса. Напишите в Telegram или WhatsApp.']);
    $t = now();
    $pdo->prepare("INSERT INTO leads(created_at,updated_at,name,contact,pain,country,consent_pd,consent_ads,consent_version,ip,user_agent,page) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")
        ->execute([$t, $t, $name, $contact, $pain, $country, 1, (($d['consent_ads'] ?? null) === true) ? 1 : 0, CONSENT_VERSION, $ip,
                   mb_substr((string)($_SERVER['HTTP_USER_AGENT'] ?? ''), 0, 300), mb_substr((string)($d['page'] ?? ''), 0, 300)]);
    $id = (int)$pdo->lastInsertId();
} catch (Throwable $ex) {
    error_log('salespeak lead: ' . $ex->getMessage());
    out(500, ['ok' => false, 'error' => 'Заявка не сохранилась. Напишите, пожалуйста, в Telegram @gavrish_anastasiya.']);
}
// ответ посетителю сразу, уведомление в Telegram – после
http_response_code(200);
echo json_encode(['ok' => true, 'id' => $id], JSON_UNESCAPED_UNICODE);
if (function_exists('fastcgi_finish_request')) fastcgi_finish_request();
notify($id);
