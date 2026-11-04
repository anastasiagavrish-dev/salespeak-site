<?php
// Забирает обновления сайта с GitHub. Запускается по расписанию из Crontab хостинга:
//   php ~/salespeak.ru/public_html/_app/update.php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require __DIR__ . '/lib.php';

const REPO = 'anastasiagavrish-dev/salespeak-site';
$root = dirname(__DIR__);
$ctx = stream_context_create(['http' => ['header' => "User-Agent: salespeak-updater\r\n", 'timeout' => 30]]);

$info = @file_get_contents('https://api.github.com/repos/' . REPO . '/commits/main', false, $ctx);
$sha = $info ? (json_decode($info, true)['sha'] ?? '') : '';
if (!preg_match('/^[0-9a-f]{40}$/', $sha)) { fwrite(STDERR, "Не удалось узнать версию на GitHub\n"); exit(1); }
$verFile = data_dir() . '/version.txt';
if (file_exists($verFile) && trim((string)file_get_contents($verFile)) === $sha) exit(0);

$zipData = @file_get_contents('https://codeload.github.com/' . REPO . '/zip/' . $sha, false, $ctx);
if (!$zipData) { fwrite(STDERR, "Не удалось скачать архив\n"); exit(1); }
$tmp = data_dir() . '/update.zip';
file_put_contents($tmp, $zipData);
$zip = new ZipArchive();
if ($zip->open($tmp) !== true) { fwrite(STDERR, "Архив поврежден\n"); exit(1); }
$n = 0;
for ($i = 0; $i < $zip->numFiles; $i++) {
    $name = $zip->getNameIndex($i);
    // в архиве путь вида salespeak-site-<sha>/public/...
    if (!preg_match('#^[^/]+/public/(.+)$#', $name, $m)) continue;
    $rel = $m[1];
    if (str_ends_with($rel, '/') || str_starts_with($rel, '_data/') || str_contains($rel, '..')) continue;
    $dest = "$root/$rel";
    if (!is_dir(dirname($dest))) mkdir(dirname($dest), 0755, true);
    file_put_contents($dest . '.tmp', $zip->getFromIndex($i));
    rename($dest . '.tmp', $dest);
    $n++;
}
$zip->close();
unlink($tmp);
file_put_contents($verFile, $sha);
echo "Обновлено до $sha, файлов: $n\n";
