<?php
// Админка заявок salespeak.ru: первый вход с кодом установки, пароль, статусы, CSV, удаление, настройки Telegram.
declare(strict_types=1);
require dirname(__DIR__) . '/_app/lib.php';

session_name('sp_admin');
session_set_cookie_params(['lifetime' => 30 * 86400, 'path' => '/admin', 'secure' => !empty($_SERVER['HTTPS']) || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https'), 'httponly' => true, 'samesite' => 'Strict']);
ini_set('session.gc_maxlifetime', (string)(30 * 86400));
session_save_path(data_dir());
session_start();
header('X-Robots-Tag: noindex, nofollow');
header('X-Frame-Options: DENY');
header('Cache-Control: no-store');

$S = settings();
$action = $_GET['a'] ?? '';
$post = ($_SERVER['REQUEST_METHOD'] ?? '') === 'POST';
if (empty($_SESSION['csrf'])) $_SESSION['csrf'] = bin2hex(random_bytes(16));
$csrf = $_SESSION['csrf'];
$csrf_ok = $post && hash_equals($csrf, (string)($_POST['csrf'] ?? ''));

function page(string $title, string $body): never {
    $css = <<<CSS
:root{--bg:#F6F6FB;--card:#FFFFFF;--fg:#17152B;--muted:#5E5C75;--line:#E1DFEE;--violet:#4B3FE1;--lime:#D6F479;--bad:#C2261B;--r:14px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:500 16px/1.5 Montserrat,system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px max(16px,env(safe-area-inset-left))}
h1{font:600 26px/1.2 Unbounded,Montserrat,system-ui,sans-serif;margin:0}h2{font-size:18px;margin:0}
.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin-bottom:20px}
.tabs{display:flex;flex-wrap:wrap;gap:8px}.tabs a{padding:8px 14px;border-radius:999px;text-decoration:none;color:var(--fg);background:var(--card);border:1px solid var(--line);font-size:14px;font-weight:600}
.tabs a.on{background:var(--fg);color:#fff;border-color:var(--fg)}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 18px;border:0;border-radius:12px;background:var(--violet);color:#fff;font:inherit;font-weight:700;font-size:15px;cursor:pointer;text-decoration:none;transition:transform .2s cubic-bezier(.34,1.56,.64,1)}
.btn:active{transform:scale(.96)}.btn.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}.btn.danger{background:var(--bad)}
.list{display:grid;gap:12px;margin-top:16px}.lead,.card{background:var(--card);border-radius:var(--r);padding:18px;display:grid;gap:10px}
.lead-top{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline}.lead-top b{font-size:18px;overflow-wrap:anywhere}
.meta{color:var(--muted);font-size:13px;overflow-wrap:anywhere}.pain{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--bg);border-radius:10px;padding:10px 12px;font-size:15px;margin:0}
.pill{font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px;border:1px solid var(--line)}
.pill.new{background:var(--lime);border-color:var(--lime)}.pill.work{background:#E7E5FF;border-color:#E7E5FF}.pill.closed{background:#EEE;border-color:#EEE;color:var(--muted)}
.acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.acts form{margin:0}
details.del summary{cursor:pointer;color:var(--bad);font-size:14px;font-weight:600;list-style:none;padding:10px 4px}
.empty{background:var(--card);border-radius:var(--r);padding:40px 24px;text-align:center;color:var(--muted)}
.pager{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.login{max-width:420px;margin:10vh auto;background:var(--card);border-radius:var(--r);padding:28px;display:grid;gap:14px}
label{font-weight:600;font-size:15px}input{width:100%;min-height:50px;padding:12px 14px;border:1.5px solid var(--line);border-radius:10px;font:inherit}
.err{color:var(--bad);font-size:14px;margin:0}.ok{color:#2E7D32;font-size:14px;margin:0}.copy{font-size:13px;color:var(--muted)}
:focus-visible{outline:3px solid var(--violet);outline-offset:2px}
CSS;
    echo '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow">'
        . '<title>' . e($title) . ' – заявки salespeak.ru</title><link rel="stylesheet" href="/assets/fonts.css"><style>' . $css . '</style></head><body>' . $body . '</body></html>';
    exit;
}

function go(string $to = '/admin/'): never { header('Location: ' . $to, true, 303); exit; }

// ---------- первый вход: задать пароль по коду установки ----------
$tokenFile = dirname(__DIR__) . '/_app/setup-token.txt';
if (empty($S['pass'])) {
    $token = file_exists($tokenFile) ? trim((string)file_get_contents($tokenFile)) : '';
    $err = '';
    if ($post) {
        $p1 = (string)($_POST['p1'] ?? ''); $p2 = (string)($_POST['p2'] ?? '');
        if ($token === '' || !hash_equals($token, (string)($_POST['code'] ?? ''))) $err = 'Код установки не подошел.';
        elseif (mb_strlen($p1) < 10) $err = 'Пароль должен быть не короче 10 символов.';
        elseif ($p1 !== $p2) $err = 'Пароли не совпадают.';
        else {
            $S['pass'] = password_hash($p1, PASSWORD_DEFAULT);
            save_settings($S);
            @unlink($tokenFile);
            session_regenerate_id(true);
            $_SESSION['ok'] = 1;
            go();
        }
    }
    $code = e((string)($_GET['code'] ?? $_POST['code'] ?? ''));
    page('Первый вход', '<form class="login" method="post"><h1>Первый вход</h1><p class="copy">Придумайте пароль для админки заявок. Сохраните его, восстановить его без доступа к хостингу нельзя.</p>'
        . '<label for="code">Код установки</label><input id="code" name="code" value="' . $code . '" required autocomplete="off">'
        . '<label for="p1">Новый пароль, от 10 символов</label><input id="p1" name="p1" type="password" autocomplete="new-password" required>'
        . '<label for="p2">Повторите пароль</label><input id="p2" name="p2" type="password" autocomplete="new-password" required>'
        . ($err ? '<p class="err" role="alert">' . e($err) . '</p>' : '') . '<button class="btn" type="submit">Сохранить пароль</button></form>');
}

// ---------- вход ----------
if ($action === 'logout' && $csrf_ok) { $_SESSION = []; session_destroy(); go(); }
if (empty($_SESSION['ok'])) {
    $err = '';
    $fails = array_filter($_SESSION['fails'] ?? [], fn($t) => $t > time() - 900);
    if ($post) {
        if (count($fails) >= 5) $err = 'Слишком много попыток. Подождите 15 минут.';
        elseif (password_verify((string)($_POST['password'] ?? ''), $S['pass'])) { session_regenerate_id(true); $_SESSION['ok'] = 1; unset($_SESSION['fails']); go(); }
        else { $fails[] = time(); $_SESSION['fails'] = $fails; $err = 'Пароль не подошел. Проверьте раскладку и попробуйте еще раз.'; }
    }
    page('Вход', '<form class="login" method="post"><h1>Заявки</h1><label for="pw">Пароль</label><input id="pw" name="password" type="password" autocomplete="current-password" required autofocus>'
        . ($err ? '<p class="err" role="alert">' . e($err) . '</p>' : '') . '<button class="btn" type="submit">Войти</button></form>');
}

// ---------- действия ----------
$pdo = db();
if ($csrf_ok && $action === 'status' && isset(STATUSES[$_POST['to'] ?? ''])) {
    $pdo->prepare("UPDATE leads SET status=?, updated_at=? WHERE id=?")->execute([$_POST['to'], now(), (int)$_POST['id']]);
    go($_POST['back'] ?? '/admin/');
}
if ($csrf_ok && $action === 'delete') {
    $pdo->prepare("DELETE FROM leads WHERE id=?")->execute([(int)$_POST['id']]);
    go($_POST['back'] ?? '/admin/');
}
if ($action === 'csv') {
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="zayavki-' . date('Y-m-d') . '.csv"');
    $out = fopen('php://output', 'w');
    fwrite($out, "\xEF\xBB\xBF");
    $cols = ['id', 'created_at', 'name', 'contact', 'pain', 'country', 'status', 'consent_ads', 'consent_version', 'ip', 'page'];
    fputcsv($out, $cols, ';');
    foreach ($pdo->query("SELECT * FROM leads ORDER BY id DESC") as $r) fputcsv($out, array_map(fn($c) => $r[$c], $cols), ';');
    exit;
}
$msg = '';
if ($action === 'settings') {
    if ($csrf_ok) {
        $S['tg_token'] = trim((string)($_POST['tg_token'] ?? ''));
        $S['tg_chat'] = trim((string)($_POST['tg_chat'] ?? ''));
        if (!empty($_POST['p1'])) {
            if (mb_strlen((string)$_POST['p1']) < 10 || $_POST['p1'] !== ($_POST['p2'] ?? '')) $msg = '<p class="err">Пароль не сменен – он короче 10 символов или не совпадает.</p>';
            else $S['pass'] = password_hash((string)$_POST['p1'], PASSWORD_DEFAULT);
        }
        save_settings($S);
        if (!$msg) $msg = '<p class="ok">Сохранено.</p>';
        if (!empty($_POST['test']) && !empty($S['tg_token'])) { notify(0); $msg .= '<p class="copy">Тестовое сообщение отправлено. Если оно не пришло, проверьте токен и chat_id.</p>'; }
    }
    page('Настройки', '<div class="wrap"><div class="bar"><h1>Настройки</h1><a class="btn ghost" href="/admin/">К заявкам</a></div>'
        . '<form class="card" method="post" action="/admin/?a=settings"><input type="hidden" name="csrf" value="' . e($csrf) . '"><h2>Уведомления в Telegram</h2>'
        . '<p class="copy">В уведомлении приходит только номер заявки, без имени и телефона клиента.</p>'
        . '<label for="t1">Токен бота от @BotFather</label><input id="t1" name="tg_token" value="' . e($S['tg_token'] ?? '') . '" autocomplete="off">'
        . '<label for="t2">Ваш chat_id</label><input id="t2" name="tg_chat" value="' . e($S['tg_chat'] ?? '') . '" autocomplete="off">'
        . '<label><input type="checkbox" name="test" value="1" style="width:auto;min-height:0"> Отправить тестовое сообщение</label>'
        . '<h2 style="margin-top:12px">Сменить пароль</h2><label for="n1">Новый пароль</label><input id="n1" name="p1" type="password" autocomplete="new-password">'
        . '<label for="n2">Повторите</label><input id="n2" name="p2" type="password" autocomplete="new-password">' . $msg
        . '<button class="btn" type="submit">Сохранить</button></form></div>');
}

// ---------- список ----------
$status = $_GET['status'] ?? 'all';
$p = max(1, (int)($_GET['p'] ?? 1));
$per = 30;
$where = isset(STATUSES[$status]) ? 'WHERE status=' . $pdo->quote($status) : '';
$total = (int)$pdo->query("SELECT COUNT(*) FROM leads $where")->fetchColumn();
$rows = $pdo->query("SELECT * FROM leads $where ORDER BY id DESC LIMIT $per OFFSET " . (($p - 1) * $per))->fetchAll();
$counts = [];
foreach (STATUSES as $k => $v) $counts[$k] = (int)$pdo->query("SELECT COUNT(*) FROM leads WHERE status=" . $pdo->quote($k))->fetchColumn();
$back = e($_SERVER['REQUEST_URI'] ?? '/admin/');
$tabs = '<a class="' . ($status === 'all' ? 'on' : '') . '" href="/admin/?status=all">Все · ' . array_sum($counts) . '</a>';
foreach (STATUSES as $k => $v) $tabs .= '<a class="' . ($status === $k ? 'on' : '') . '" href="/admin/?status=' . $k . '">' . $v . ' · ' . $counts[$k] . '</a>';
$items = '';
foreach ($rows as $r) {
    $btns = '';
    foreach (STATUSES as $k => $v) if ($k !== $r['status'])
        $btns .= '<form method="post" action="/admin/?a=status"><input type="hidden" name="csrf" value="' . e($csrf) . '"><input type="hidden" name="id" value="' . (int)$r['id'] . '"><input type="hidden" name="to" value="' . $k . '"><input type="hidden" name="back" value="' . $back . '"><button class="btn ghost" type="submit">' . $v . '</button></form>';
    $t = date('d.m.Y H:i', strtotime($r['created_at']) + 5 * 3600) . ' (Алматы)';
    $items .= '<article class="lead"><div class="lead-top"><b>' . e($r['name']) . '</b><span>' . e($r['contact']) . '</span><span class="pill ' . e($r['status']) . '">' . e(STATUSES[$r['status']] ?? $r['status']) . '</span></div>'
        . ($r['pain'] ? '<p class="pain">' . e($r['pain']) . '</p>' : '')
        . '<p class="meta">№' . (int)$r['id'] . ' · ' . $t . ' · страна: ' . e($r['country'] ?: 'по номеру') . ' · рассылка: ' . ($r['consent_ads'] ? 'да' : 'нет') . ' · согласие ' . e($r['consent_version']) . ' · IP ' . e($r['ip']) . '</p>'
        . '<div class="acts">' . $btns . '<details class="del"><summary>Удалить</summary><form method="post" action="/admin/?a=delete"><input type="hidden" name="csrf" value="' . e($csrf) . '"><input type="hidden" name="id" value="' . (int)$r['id'] . '"><input type="hidden" name="back" value="' . $back . '"><button class="btn danger" type="submit">Удалить заявку №' . (int)$r['id'] . ' навсегда</button></form></details></div></article>';
}
if ($items === '') $items = '<div class="empty">Заявок пока нет. Как только кто-то заполнит форму на сайте, она появится здесь.</div>';
$pages = (int)ceil($total / $per);
$pager = '';
if ($pages > 1) { $pager = '<nav class="pager">'; for ($i = 1; $i <= $pages; $i++) $pager .= '<a class="btn ' . ($i === $p ? '' : 'ghost') . '" href="/admin/?status=' . e($status) . '&p=' . $i . '">' . $i . '</a>'; $pager .= '</nav>'; }
$tgHint = empty($S['tg_token']) ? '<p class="copy">Уведомления в Telegram не настроены – <a href="/admin/?a=settings">настроить</a>.</p>' : '';
page('Заявки', '<div class="wrap"><div class="bar"><h1>Заявки</h1><div class="acts"><a class="btn ghost" href="/admin/?a=csv">Скачать CSV</a><a class="btn ghost" href="/admin/?a=settings">Настройки</a>'
    . '<form method="post" action="/admin/?a=logout"><input type="hidden" name="csrf" value="' . e($csrf) . '"><button class="btn ghost" type="submit">Выйти</button></form></div></div>'
    . $tgHint . '<nav class="tabs" aria-label="Статусы">' . $tabs . '</nav><div class="list">' . $items . '</div>' . $pager
    . '<p class="copy" style="margin-top:24px">Заявки хранятся 3 года с последнего изменения и удаляются автоматически. Запрос «удалите мои данные» – найдите заявку и нажмите «Удалить».</p></div>');
