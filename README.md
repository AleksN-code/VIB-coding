Назва: # VIB-coding
Мета: навчання основам створювання проєківи за допомогою штучного інтелекту
Базові можливості: Отримання навичок кодінгу
Користувач: для аналітиків
Створення продукту

## Урок 3: перший Telegram-бот

### Що робить бот

Мінімальний навчальний Telegram-бот на [aiogram 3](https://docs.aiogram.dev/). Він вітається на `/start`, одразу показує список своїх команд і пояснює, що вміє, на `/help`.

Токен бота читається зі змінної середовища `BOT_TOKEN`. Локально її завантажує з файлу `.env` бібліотека python-dotenv, а в Docker її передає `docker-compose.yml`.

### Доступні команди

| Команда | Що робить |
|---|---|
| `/start` | привітання і список усіх команд |
| `/help` | коротко пояснює, що робить бот, і показує доступні команди |

### Структура

| Файл | Призначення |
|---|---|
| `app/main.py` | код Telegram-бота |
| `requirements.txt` | Python-залежності: `aiogram`, `python-dotenv`, `watchfiles` |
| `.env` | реальний `BOT_TOKEN`, тільки локально (не потрапляє в Git) |
| `.env.example` | приклад змінної без реального токена |
| `.gitignore` | файли, які не повинні потрапити в Git |
| `Dockerfile` | правила створення Docker image |
| `docker-compose.yml` | запуск контейнера в режимі розробки з automatic restart |

### 1. Створити `.env`

1. Відкрийте в Telegram [@BotFather](https://t.me/BotFather), надішліть `/newbot`, вкажіть назву та username бота (має закінчуватися на `bot`) і скопіюйте токен.
2. Створіть `.env` з прикладу:

   ```powershell
   Copy-Item .env.example .env      # Windows PowerShell
   cp .env.example .env             # macOS / Linux
   ```

3. Відкрийте `.env` і вставте свій токен:

   ```
   BOT_TOKEN=123456789:AA...
   ```

Токен — це пароль від бота. `.env` вже додано в `.gitignore`: не комітьте його і не публікуйте токен.

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
