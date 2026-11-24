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

**Варіант тієї самої ситуації:** якщо запуск перервано саме під час завантаження бібліотеки pydantic (її використовує aiogram), замість `KeyboardInterrupt` в останньому рядку буде:

```
  KeyboardInterrupt:
pyo3_runtime.PanicException: Error building schema validator:
  KeyboardInterrupt:
```

Причина та сама — перед цим у логах кілька `1 change detected` поспіль, а після — нормальний `Start polling`.

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

## 5. Авто не додається: бот мовчить (`Update ... is not handled`)

**Коли:** перша версія команди `/addcar`. Користувач натиснув `/addcar` у списку команд, отримав підказку з форматом і надіслав дані авто (`BMW X5 2018`) окремим повідомленням.

**Що бачив користувач:** бот відповів підказкою на `/addcar`, а на `BMW X5 2018` — нічого. Авто в базі не з'явилося.

**Повідомлення** (`docker compose logs bot`) — помилок немає, але частина оновлень не оброблена:

```
INFO | aiogram.event | Update id=836014079 is handled. Duration 80 ms ...
INFO | aiogram.event | Update id=836014080 is not handled. Duration 0 ms ...
```

Перевірка в базі через `psql`: `users` — 1, `cars` — 0.

**Причина:** помилка в дизайні бота, а не в даних користувача.

- Перша версія розуміла дані авто лише в тому самому повідомленні, що й команда: `/addcar BMW X5 2018`.
- Коли команду натискають у списку, Telegram надсилає `/addcar` **без даних**.
- Наступне повідомлення `BMW X5 2018` — звичайний текст. Жоден обробник на нього не був розрахований, тому aiogram пропустив його (`is not handled`), а бот нічого не відповів.

**Виправлення:**

1. Після `/addcar` без даних бот переходить у стан «чекаю дані авто» (FSM, `AddCarForm.entering_car`) і приймає наступне повідомлення як марку, модель і рік.
2. Якщо дані неправильні, бот пояснює помилку і лишається на цьому кроці.
3. Додано обробник «усе інше» (`unknown_message`): на будь-яке незрозуміле повідомлення бот відповідає «Не зрозумів повідомлення» і показує меню — бот більше ніколи не мовчить.
4. Додано кнопки меню («🚗 Додати авто» тощо), щоб не потрібно було пам'ятати формат команд.

**Перевірка:** «🚗 Додати авто» → `BMW X5 2018` → бот відповідає «✅ Авто додано», у логах:

```
INFO | __main__ | Додано авто car_id=... від user_id=...
```

**Висновок:** рядки `is not handled` у логах — ознака того, що користувач робить щось, чого бот не очікує. Їх варто перевіряти, навіть коли помилок немає.

## 6. Перехід на Alembic: таблиці вже існують

**Коли:** підключення міграцій Alembic до бази, яку раніше створив сам бот (`Base.metadata.create_all`). У базі вже були 4 таблиці й справжні дані — 5 витрат по BMW X6.

**Що сталося б без підготовки.** Перша міграція `0001_initial` створює таблиці. На базі, де вони вже є, `alembic upgrade head` упав би:

```
sqlalchemy.exc.ProgrammingError: (psycopg.errors.DuplicateTable) relation "categories" already exists
```

а сервіс `migrate` завершився б з `Exited (1)` — і бот з API не запустилися б (вони чекають на успішні міграції).

**Причина:** Alembic зберігає версію схеми в таблиці `alembic_version`. Її не було, тож Alembic вважав базу порожньою і почав би з першої міграції.

**Що зробили** (помилки так і не виникло):

1. Перевірили, що база **точно** відповідає `0001`: однакові таблиці, колонки, типи; `alembic_version` немає.
2. Позначили базу як таку, що вже має версію `0001`, нічого не виконуючи:

   ```powershell
   docker compose run --rm migrate alembic stamp 0001
   ```

3. Застосували лише нову міграцію: `docker compose run --rm migrate` → `Running upgrade 0001 -> 0002`.
4. Звірили результат через `psql` і `alembic check` → `No new upgrade operations detected`.

PostgreSQL виконує міграцію в одній транзакції: якби `0002` упала посередині, база лишилася б як до неї.

**Перевірка:**

```powershell
docker compose run --rm migrate alembic current    # 0002 (head)
```

**Висновок:** `stamp` потрібен один раз — для бази, створеної до Alembic. Нова порожня база (наприклад, на Render) отримує всю схему звичайним `alembic upgrade head`.

## 7. Адмінка: «Backend API не відповідає (HTTP 500)»

**Коли:** змодельовано навмисно — зупинили сервіс API, адмінка лишилася запущеною:

```powershell
docker compose stop api
```

**Що бачить користувач:** в адмінці замість даних — блок «Не вдалося отримати дані: Backend API не відповідає (HTTP 500)» зі списком, що перевірити, і кнопкою «Спробувати ще раз».

**Відповідь на запит** `http://localhost:5173/api/summary`:

```
HTTP 500, content-type: text/plain   (порожня відповідь)
```

**Причина:** браузер звертається не до API напряму, а до dev-сервера Vite (`localhost:5173/api/...`), який пересилає запит на `api:8000`. Коли API зупинений, пересилати нікуди — і вже Vite відповідає `500` не в JSON. `frontend/src/api.js` розпізнає саме цей випадок (помилка + не JSON) і показує зрозумілий текст замість технічної помилки.

**Виправлення:**

```powershell
docker compose ps              # api — не running?
docker compose up -d api       # запустити
docker compose logs api        # якщо не стартує — шукати причину тут
```

Потім в адмінці — «Спробувати ще раз».

**Перевірка:** http://localhost:8000/api/health → `{"status":"ok"}`, адмінка показує дані.

**Чим відрізняються помилки:**

| Що в адмінці | Де проблема |
|---|---|
| «Backend API не відповідає (HTTP 500)» | API не запущений або впав — `docker compose logs api` |
| «API повернув помилку 503: База даних тимчасово недоступна» | API працює, але не може дістатися до Neon — перевірити `DATABASE_URL` і доступ до інтернету |
| «Немає з'єднання з backend API» | не запущений сам `frontend` або немає мережі |

## 8. Номери записів «стрибають» (категорія з id 61)

**Коли:** після міграції `0002` нова категорія «Продаж авто» отримала номер **61**, а не 7. Так само номери користувачів і операцій починалися не з 1.

**Причина:** номери (`id`) видає лічильник PostgreSQL (sequence), і він **ніколи не повертає вже виданий номер** — навіть якщо запис не зберігся:

- стара версія бота під час кожного запуску намагалася додати 6 категорій (`INSERT … ON CONFLICT DO NOTHING`). Категорії вже були, запис не відбувався, але лічильник щоразу витрачав 6 номерів. За ~9 перезапусків — понад 50 номерів;
- тести в транзакціях, які потім скасовували, теж витрачали номери.

**Чи це проблема:** ні. `id` — лише унікальний ідентифікатор, а не порядковий номер; пропуски нормальні для будь-якої бази. Покладатися на «id без пропусків» не можна.

**Що змінилося:** категорії тепер створюють міграції — один раз, а не під час кожного запуску бота.
