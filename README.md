# salespeak.ru

Сайт Анастасии Гавриш, эксперта по продажам.

- `content.py` – тексты услуг и кейсов
- `gen.py` – сборка сайта в `public/` (`python3 gen.py`)
- `src/` – стили, скрипты, изображения
- `public/` – готовый сайт, его отдает nginx
- `backend/main.py` – прием заявок и админка (FastAPI + SQLite)
- `deploy/` – установка на сервер и автообновление каждые 10 минут

Установка на чистый Ubuntu (под root):

    curl -fsSL https://raw.githubusercontent.com/anastasiagavrish-dev/salespeak-site/main/deploy/install.sh | bash -s -- ru   # сервер в России
    curl -fsSL https://raw.githubusercontent.com/anastasiagavrish-dev/salespeak-site/main/deploy/install.sh | bash -s -- kz   # сервер в Казахстане
