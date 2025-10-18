# Truth Social → Telegram Keyword Alerts Bot

Этот небольшой сервис на Python следит за выбранными аккаунтами в Truth Social и присылает уведомления в Telegram, если в новом посте встречаются нужные ключевые слова.

Поддерживаются два режима:
1) **API режим (совместимые с Mastodon эндпоинты)** — быстрый и лёгкий. Пытается сначала.
2) **Fallback-скрейпинг через Playwright** — если API недоступен/заблокирован, бот может читать страницу пользователя в headless Chromium.

> ⚠️ Используйте ответственно. Соблюдайте условия использования сайтов и законы вашей юрисдикции.

---

## Быстрый старт

1. Установите Python 3.10+.
2. Распакуйте файлы из этого архива в папку (или клонируйте содержимое).
3. Создайте Telegram‑бота через **@BotFather** и получите **Bot Token**.
4. Узнайте свой **Chat ID** (например, напишите что‑нибудь вашему боту и используйте @userinfobot или бота один раз добавьте в канал/группу и возьмите ID).
5. Заполните `.env` по шаблону (укажите токен, chat id, список пользователей и ключевые слова).
6. Установите зависимости:
   ```bash
   python -m venv .venv && . .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
7. (Для fallback) Установите движок браузера Playwright один раз:
   ```bash
   playwright install chromium
   ```
8. Запустите бот:
   ```bash
   python bot_truth_watch.py
   ```

---

## Настройки (.env)

```ini
TELEGRAM_BOT_TOKEN=...          # Токен вашего бота
TELEGRAM_CHAT_ID=...            # Куда присылать уведомления (личка/канал/группа)
USERS=realDonaldTrump,kariLake  # Список логинов Truth Social без @
KEYWORDS=bitcoin,btc,fed,...    # Ключевые слова (регистр не важен)
POLL_INTERVAL_SECONDS=45        # Интервал опроса
USE_PLAYWRIGHT_FALLBACK=true    # Включить резервный способ через Playwright
REQUEST_TIMEOUT_SECONDS=20
HTTP_PROXY=                     # (опционально) прокси
HTTPS_PROXY=
```

Ключевые слова ищутся простым подстрочным поиском. Хотите точнее — используйте регулярные выражения/стемминг (легко расширить в коде).

---

## Как это работает

- Сначала бот пробует **API** (эндпоинты `.../api/v1/...`). Если получилось — берём свежие посты нужного пользователя.
- Если API недоступен и включён `USE_PLAYWRIGHT_FALLBACK`, используется скрейпинг через **Playwright** (Chromium) для чтения страницы и извлечения текста.
- Для каждого поста проверяются ключевые слова; при совпадении отправляется сообщение в Telegram (с ссылкой на пост).
- Память о «последнем увиденном посте» хранится в оперативке (для простоты).

> Для стойкости к перезапускам можно заменить словарь `last_seen` на SQLite — заготовка легко добавляется в код.

---

## Запуск как сервис (Linux, systemd)

Создайте файл `/etc/systemd/system/truthwatch.service`:
```ini
[Unit]
Description=Truth Social → Telegram watcher
After=network-online.target

[Service]
WorkingDirectory=/opt/truthwatch
ExecStart=/usr/bin/python3 /opt/truthwatch/bot_truth_watch.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Далее:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now truthwatch.service
journalctl -u truthwatch.service -f
```

---

## Полезные советы

- Увеличьте `POLL_INTERVAL_SECONDS`, если получите 429/ограничения.
- Для нескольких чатов используйте список chat id или сделайте маршрутизацию по ключевым словам.
- Для точного соответствия ключевых слов можно заменить простую проверку на `re.compile(...)` и границы слова `\b`.
- Соблюдайте rate‑limit и правила площадки. Храните токены в секрете.

Удачи! 🚀
