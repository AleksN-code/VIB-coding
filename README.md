# VIB-coding

## Про проєкт

**Мета:** навчитися основ створення програмних проєктів за допомогою штучного інтелекту.

**Для кого:** аналітики, які хочуть отримати навички програмування.

**Що дає:**

- навички кодингу на практиці;
- створення власного продукту — від налаштування середовища до робочого Telegram-бота.

**Історія навчання:**

- перевірка середовища (Docker, WSL 2, nginx, ngrok) — [environment-check.md](environment-check.md);
- урок 3 — перший Telegram-бот (нижче);
- урок 4 — логування, помилки та перевірка секретів — [Debug / Troubleshooting](#debug--troubleshooting), [DEBUG.md](DEBUG.md), [detect-secrets](#перевірка-секретів-detect-secrets);
- архітектура продукту — frontend, backend, database, API — [docs/architecture.md](docs/architecture.md);
- база даних і запис витрат — Neon PostgreSQL, SQLAlchemy, схема — [docs/database.md](docs/database.md), [запис витрат](#запис-витрат-у-базу);
- безпека секретів — [docs/security.md](docs/security.md).

## Урок 3: перший Telegram-бот

### Що робить бот

Telegram-бот на [aiogram 3](https://docs.aiogram.dev/) для обліку витрат на пригін, ремонт і продаж авто. Користувач додає свої авто, записує витрати до кожного з них і бачить, скільки вже вкладено в кожне авто. Дані зберігаються в базі [Neon PostgreSQL](https://neon.tech).

Секрети — `BOT_TOKEN` і `DATABASE_URL` — читаються зі змінних середовища. Локально їх завантажує з файлу `.env` бібліотека python-dotenv, а в Docker їх передає `docker-compose.yml`.

### Доступні команди

Після `/start` внизу екрана з'являються кнопки меню. Ті самі дії доступні командами і через кнопку «Меню» біля поля вводу.

| Кнопка | Команда | Що робить |
|---|---|---|
| — | `/start` | привітання, список команд і кнопки меню |
| 🚗 Додати авто | `/addcar` | додати авто: марка, модель, рік, VIN (необов'язково). Можна одразу: `/addcar BMW X5 2018` |
| 📋 Мої авто | `/cars` | список авто і скільки витрачено на кожне |
| 💸 Додати витрату | `/expense` | обрати авто → категорію → написати суму й опис (`450 заміна фар`) |
| — | `/cancel` | скасувати поточну дію |
| ❓ Допомога | `/help` | що вміє бот і як ним користуватися |

### Структура

| Файл | Призначення |
|---|---|
| `app/main.py` | обробники команд і кнопок, меню, запуск бота |
| `app/crud.py` | операції з базою: користувачі, авто, категорії, витрати |
| `app/models.py` | таблиці бази як класи SQLAlchemy |
| `app/db.py` | підключення до Neon, створення таблиць і категорій |
| `requirements.txt` | Python-залежності: `aiogram`, `python-dotenv`, `watchfiles`, `SQLAlchemy`, `psycopg` |
| `.env` | справжні `BOT_TOKEN` і `DATABASE_URL`, тільки локально (не потрапляє в Git) |
| `.env.example` | приклад змінних без справжніх значень |
| `.gitignore` | файли, які не повинні потрапити в Git |
| `Dockerfile` | правила створення Docker image |
| `docker-compose.yml` | запуск бота в режимі розробки з automatic restart і сервіс перевірки секретів |
| `.dockerignore` | файли, які не передаються в Docker під час збирання образу (зокрема `.env`) |
| `DEBUG.md` | опис помилок, які траплялися в проєкті, і як їх виправити |
| `docs/architecture.md` | блоки продукту, як працюють `/start` і запис витрати |
| `docs/database.md` | таблиці, поля і зв'язки бази, схема з dbdiagram |
| `docs/security.md` | секрети проєкту, `.env` і `.env.example`, що робити при витоку |

### 1. Створити `.env`

1. **Токен бота.** Відкрийте в Telegram [@BotFather](https://t.me/BotFather), надішліть `/newbot`, вкажіть назву та username бота (має закінчуватися на `bot`) і скопіюйте токен.
2. **База даних.** Зареєструйтеся на [console.neon.tech](https://console.neon.tech), створіть проєкт, натисніть **Connect** і скопіюйте **Connection string** (починається з `postgresql://`).
3. Створіть `.env` з прикладу:

   ```powershell
   Copy-Item .env.example .env      # Windows PowerShell
   cp .env.example .env             # macOS / Linux
   ```

4. Відкрийте `.env` і вставте обидва значення:

   ```
   BOT_TOKEN=<токен від BotFather>
   DATABASE_URL=<Connection string з Neon>
   ```

Токен і рядок підключення — це паролі від бота й бази. `.env` вже додано в `.gitignore`: не комітьте його і не публікуйте ці значення. Детальніше — [docs/security.md](docs/security.md).

Таблиці в базі й категорії витрат бот створює сам під час першого запуску.

> Не запускайте одночасно локальну та Docker-версію бота: два процеси з одним `BOT_TOKEN` конфліктують.

### 2. Встановити залежності (для локального запуску)

Потрібен Python 3. Створіть віртуальне середовище і встановіть залежності:

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS або Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Для запуску через Docker цей крок не потрібен: залежності встановлюються всередині образу.

### 3. Запустити локально

З активованим віртуальним середовищем:

```powershell
python -m app.main
```

Відкрийте свого бота в Telegram і надішліть `/start`. У терміналі не повинно бути traceback. Зупинка: `Ctrl + C`.

### 4. Запустити через Docker Compose

Docker Desktop має бути запущений.

```powershell
docker compose up --build
```

Відкрийте свого бота в Telegram і надішліть `/start`. Зупинка: `Ctrl + C`.

Корисні команди:

```powershell
docker compose up -d --build   # запуск у фоні
docker compose ps              # стан контейнера
docker compose logs -f         # логи
docker compose down            # зупинити й видалити контейнер
```

Перезбирати образ (`--build`) потрібно лише після змін у `requirements.txt` або `Dockerfile`. Зміни в коді в папці `app` підхоплюються автоматично (див. нижче).

### 5. Перевірити automatic restart

`docker-compose.yml` запускає бота в режимі розробки:

- локальна папка `app` підключена в контейнер (`volumes: ./app:/bot/app`);
- бот запускається через [watchfiles](https://watchfiles.helpmanual.io/), який перезапускає `python -m app.main` після зміни будь-якого `.py` файлу в `app`;
- `WATCHFILES_FORCE_POLLING=true` — на Windows/WSL 2 події зміни файлів не доходять у контейнер, тому watcher перевіряє файли опитуванням.

Як перевірити:

1. Запустіть бота у фоні: `docker compose up -d --build`.
2. Відкрийте логи: `docker compose logs -f`.
3. Змініть і збережіть `app/main.py` (наприклад, текст привітання).
4. За кілька секунд у логах з'явиться:

   ```
   1 change detected
   Polling stopped ...
   Start polling
   Run polling for bot @<ваш_бот>
   ```

5. Надішліть `/start` у Telegram — бот відповість уже новим текстом.

Якщо зберегти файл кілька разів поспіль, у логах може з'явитися `KeyboardInterrupt`: watcher перервав попередній запуск. Це не помилка — після цього бот запускається нормально.

### Яку маленьку функцію було додано

Після робочої команди `/start` додано команду **`/help`**: вона коротко пояснює, що робить бот, і показує доступні команди. Також `/start` тепер одразу виводить список команд.

Список команд зберігається в одній змінній `COMMANDS_TEXT` в `app/main.py` і використовується в обох командах. Щоб додати нову команду в список, достатньо дописати один рядок.

### Що перевірялося після роботи AI

- `git status` — змінено лише файли, потрібні для задачі, без зайвих змін.
- `git diff` — переглянуто кожну зміну в коді.
- `BOT_TOKEN` читається зі змінної середовища (`os.getenv("BOT_TOKEN")`), а якщо його немає — бот зупиняється з поясненням.
- Реального токена немає в коді, README та `.env.example` (файли в Git перевірено пошуком рядків, схожих на токен).
- `.env` не відображається в `git status` і не потрапляє в Git (`git check-ignore .env`).
- `.env` не копіюється в Docker image: `Dockerfile` копіює лише папку `app/`.
- Бот запускається в Docker без traceback, `/start` і `/help` відповідають у Telegram.
- Automatic restart працює: після зміни `app/main.py` бот сам перезапускається.

## Запис витрат у базу

Маршрут запиту:

```
Telegram → Telegram Bot API → aiogram backend → SQLAlchemy → Neon PostgreSQL
```

- **SQLAlchemy** допомагає Python-коду працювати з базою: таблиці описані класами в `app/models.py`, запити — у `app/crud.py`.
- **Neon** — сама PostgreSQL-база в хмарі. Рядок підключення — у `DATABASE_URL`.

Схема бази (users, cars, categories, transactions) — у [docs/database.md](docs/database.md), як проходить запис витрати через усі блоки — у [docs/architecture.md](docs/architecture.md#як-працює-запис-витрати).

### Як записати витрату

1. **🚗 Додати авто** → напишіть `BMW X5 2018` (або з VIN: `BMW X5 2018 WBAXXXXXXXXXXXXXX`).
2. **💸 Додати витрату** → натисніть авто → натисніть категорію → напишіть `450 заміна фар`.
3. Бот відповість «✅ Витрату записано» і покаже, скільки всього витрачено на це авто.
4. **📋 Мої авто** — усі авто із сумою витрат.

Сума — число без пробілів, за потреби з копійками через крапку чи кому (`1250,50`), опис — після пробілу.

### Як перевірити, що дані в базі

- **Neon Console** → проєкт → **Tables** — переглянути таблиці `users`, `cars`, `transactions`.
- Або **SQL Editor** у Neon Console:

  ```sql
  select c.brand, c.model, c.year, cat.name, t.amount, t.description, t.created_at
  from transactions t
  join cars c on c.id = t.car_id
  join categories cat on cat.id = t.category_id
  order by t.created_at desc;
  ```

### Що перевірялося

- Підключення до Neon із контейнера бота через SQLAlchemy + psycopg.
- Таблиці й 6 категорій створюються під час старту, повторний запуск нічого не дублює.
- Розбір авто (марка, модель, рік, VIN) і суми: неправильні рік, VIN, `0`, `-5`, `12.345`, `1e3`, `1 200` — відхиляються з поясненням.
- Користувач не бачить і не може використати чужі авто.
- База сама не дає записати суму ≤ 0 (`CHECK (amount > 0)`).
- Тести роботи з базою виконувалися в транзакції, яку потім скасовано — тестових даних у базі не лишилося.
- `DATABASE_URL` не потрапляє в Git, Docker image і логи; detect-secrets — чисто.

## Debug / Troubleshooting

Спершу подивіться логи — бот пише в них старт і кожну команду:

```powershell
docker compose logs -f bot
```

Бот працює, якщо в логах є `Run polling for bot @<ваш_бот>`. Статус `running` у `docker compose ps` ще нічого не гарантує: watcher може працювати, навіть коли бот упав.

| Симптом | Що зробити |
|---|---|
| `failed to connect to the docker API` | запустити Docker Desktop і дочекатися завантаження |
| `TelegramUnauthorizedError: ... Unauthorized` | неправильний токен — перевірити `BOT_TOKEN` у `.env`, потім `docker compose up -d --force-recreate` |
| `TokenValidationError: Token is invalid!` | токен у неправильному форматі — скопіювати його з @BotFather повністю |
| `Не задано BOT_TOKEN` / `Не задано DATABASE_URL` | створити `.env` з `.env.example` і вставити значення |
| `OperationalError` / `password authentication failed` під час старту | неправильний `DATABASE_URL` або пароль бази змінено — скопіювати рядок заново з Neon (**Connect**), потім `docker compose up -d --force-recreate` |
| `KeyboardInterrupt` або `PanicException` після збереження файлу | не помилка: watcher перезапустив бота посеред запуску — далі має бути `Start polling` |
| бот відповідає «Ця кнопка вже не діє» | бот перезапускався, незавершений запис загубився — почати заново: 💸 Додати витрату |
| у логах `Update ... is not handled` | повідомлення не підійшло жодному обробнику — див. [DEBUG.md](DEBUG.md), розділ 5 |
| бот не відповідає, а в логах `Conflict: terminated by other getUpdates request` | бот запущено двічі (локально і в Docker) — зупинити одну копію |
| зміни в `.env` не діють | `restart` не перечитує `.env` — потрібен `docker compose up -d --force-recreate` |

Детальний опис помилок, які траплялися в проєкті, з повідомленнями та поясненнями — у [DEBUG.md](DEBUG.md).

## Перевірка секретів (detect-secrets)

[detect-secrets](https://github.com/Yelp/detect-secrets) шукає токени, паролі та ключі у файлах, які відстежує Git (`.env` у Git немає, тому не перевіряється). Запускайте перевірку перед кожним комітом.

Python на ПК не потрібен: сканер запускається в Docker як окремий сервіс `secrets-scan` у `docker-compose.yml`. Разом із ботом він не стартує.

| Файл | Призначення |
|---|---|
| `.secrets.baseline` | список уже відомих знахідок; ті, що позначені `"is_secret": false`, — хибні спрацювання |
| `tools/detect_secrets_telegram.py` | плагін, який знаходить Telegram bot token у будь-якому місці рядка — вбудований детектор бачить токен, лише якщо той займає весь рядок, і пропускає `BOT_TOKEN = "..."` |

### Перевірити проєкт

```powershell
docker compose run --rm secrets-scan
```

- `detect-secrets - нових секретів не знайдено` — усе гаразд, можна комітити.
- `ERROR: Potential secrets about to be committed to git repo!` — знайдено новий секрет. У виводі є файл і рядок: приберіть секрет із файлу (перенесіть у `.env`). Якщо секрет уже потрапив на GitHub — відкличте його (для бота: `/revoke` у @BotFather) і створіть новий.

Перший запуск довший: Docker збирає образ зі сканером.

### Якщо це хибне спрацювання

Наприклад, вигаданий токен у документації. Оновіть baseline і позначте знахідку як не секрет:

```powershell
docker compose run --rm secrets-scan "detect-secrets scan --baseline .secrets.baseline"
docker compose run --rm secrets-scan "detect-secrets audit .secrets.baseline"
```

В `audit` на кожну знахідку відповідайте `n` (це не секрет) або `y` (це справжній секрет — його треба прибрати з файлу). Після цього закомітьте оновлений `.secrets.baseline`.
