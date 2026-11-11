# DEBUG

Помилки, які траплялися під час роботи над Telegram-ботом, і як їх виправили.

## 1. Docker не запущений

**Коли:** під час збирання образу бота командою `docker compose build` / `docker compose up --build`.

**Повідомлення:**

```
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine;
check if the path is correct and if the daemon is running:
open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

**Причина:** Docker встановлений, але Docker Desktop не був запущений. Команда `docker` є, а Docker Engine, до якого вона звертається, — ні. Docker Desktop не стартує сам після перезавантаження ПК, якщо це не налаштовано.

**Виправлення:** запустити Docker Desktop через меню «Пуск» і дочекатися, поки він повністю завантажиться.

**Перевірка:**

```powershell
docker info --format "{{.ServerVersion}}"
```

Команда має вивести версію (наприклад, `29.9.2`), а не помилку.

## 2. Тунель ngrok не запускався без authtoken

**Коли:** під час спроби відкрити nginx в інтернет командою `ngrok http 8080`.

**Повідомлення** (від `ngrok config check`):

```
ERROR:  GetFileAttributesEx C:\Users\<user>\AppData\Local\ngrok\ngrok.yml:
The system cannot find the path specified.
```

**Причина:** ngrok був встановлений, але не налаштований: файлу конфігурації з токеном акаунта ще не існувало. Без authtoken ngrok v3 не відкриває тунелі.

**Виправлення:** взяти authtoken на https://dashboard.ngrok.com/get-started/your-authtoken і виконати:

```powershell
ngrok config add-authtoken <ВАШ_ТОКЕН>
```

Токен — секрет: його вводять самостійно в терміналі, не вставляють у чат, код або репозиторій.

**Перевірка:**

```powershell
ngrok config check
```

Має вивести `Valid configuration file at ...`.

## 3. `KeyboardInterrupt` у логах бота після збереження файлу

**Коли:** у режимі розробки з automatic restart (watchfiles у `docker-compose.yml`), коли `app/main.py` було збережено двічі з інтервалом приблизно в секунду.

**Повідомлення** (`docker compose logs bot`):

```
[08:40:00] 1 change detected
...
[08:40:01] 1 change detected
Traceback (most recent call last):
  ...
  File "/bot/app/main.py", line 3, in <module>
    import asyncio
  ...
KeyboardInterrupt
INFO:aiogram.dispatcher:Start polling
```

**Причина:** watchfiles на кожну зміну зупиняє бота і запускає його знову. Друга зміна прийшла, коли бот ще стартував після першої, тому watcher перервав цей запуск сигналом — Python показав це як `KeyboardInterrupt`. Помилки в коді немає.

**Виправлення:** нічого виправляти не потрібно — одразу після цього бот запускається нормально. Щоб такого не було, достатньо зберігати файл один раз. Те саме буває при перемиканні гілок Git, коли файли в `app/` змінюються кілька разів поспіль.

**Перевірка:** останні рядки логів мають бути без помилок:

```
INFO | aiogram.dispatcher | Start polling
INFO | aiogram.dispatcher | Run polling for bot @<ваш_бот>
```

Якщо ж traceback закінчується не `KeyboardInterrupt`, а, наприклад, `SyntaxError` або `NameError`, і після нього немає `Start polling` — це справжня помилка в коді, її треба виправити в `app/main.py`.

## 4. Неправильний токен бота (`TelegramUnauthorizedError`)

**Коли:** змодельовано навмисно — у `.env` справжній токен замінили на вигаданий у правильному форматі й перестворили контейнер:

```
BOT_TOKEN=123456789:AAwrong-token-for-debug-test-1234567
```

```powershell
docker compose up -d --force-recreate
```

**Повідомлення** (`docker compose logs bot`):

```
INFO | __main__ | Бот запускається
INFO | aiogram.dispatcher | Start polling
INFO | aiogram.dispatcher | Polling stopped
Traceback (most recent call last):
  ...
  File "/bot/app/main.py", line 50, in main
    await dp.start_polling(bot)
  ...
    user: User = await bot.me()
  ...
aiogram.exceptions.TelegramUnauthorizedError: Telegram server says - Unauthorized
```

**Причина:** формат токена правильний (`<цифри>:<символи>`), тому бот починає запуск. Але перед отриманням повідомлень aiogram запитує в Telegram дані бота (метод `getMe`), і Telegram відповідає `Unauthorized` — бота з таким токеном не існує. Так само буде, якщо токен скопійовано з помилкою або його відкликали в @BotFather (`/revoke`).

**На що звернути увагу:** контейнер при цьому залишається в стані `running` (`docker compose ps`), бо watchfiles продовжує працювати й чекає на зміни коду. Тобто за статусом контейнера проблему не видно — тільки за логами: є `Polling stopped` і traceback, а рядка `Run polling for bot @...` немає. Бот на повідомлення не відповідає.

Якщо токен має неправильний формат (наприклад, `BOT_TOKEN=abc`), помилка буде інша — `TokenValidationError: Token is invalid!`: aiogram відхиляє такий токен ще до звернення до Telegram.

**Виправлення:**

1. Перевірити токен у @BotFather (`/mybots` → бот → **API Token**) і вставити його в `.env` повністю, без пробілів і лапок.
2. Перестворити контейнер — `docker compose restart` і watcher не підхоплюють змін у `.env`, бо змінні середовища читаються лише при створенні контейнера:

   ```powershell
   docker compose up -d --force-recreate
   ```

**Перевірка:** у логах має з'явитися рядок з іменем бота:

```
INFO | aiogram.dispatcher | Run polling for bot @<ваш_бот>
```
