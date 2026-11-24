# Схема бази даних

База даних продукту для обліку витрат і продажу авто: її спільно використовують Telegram-бот (записує операції) і web-адмінка (показує їх через backend API).

- **Де:** [Neon](https://neon.tech) — PostgreSQL у хмарі.
- **Як код із нею працює:** через SQLAlchemy — моделі в [app/models.py](../app/models.py) (спільні для бота й API), підключення в [app/db.py](../app/db.py).
- **Як змінюється структура:** лише міграціями Alembic — [migrations/versions/](../migrations/versions/). Див. [Міграції](#міграції).
- **Чому схема саме така** — розділ Database в [architecture.md](architecture.md#database).

Цей файл — схема та документація бази, а не сама база.

## Діаграма

![Схема бази в dbdiagram](../images/dbdiagram.png)

## Таблиці

Чотири таблиці. В усіх є:

- `id` — унікальний номер запису, база призначає його сама;
- `created_at` — дата й час створення запису з часовим поясом, база ставить його сама.

### users — користувачі Telegram

Хто користується ботом. Запис з'являється автоматично, коли користувач уперше додає авто, переглядає свої авто або записує операцію. Якщо користувач змінив username чи ім'я в Telegram, бот оновлює їх при наступній дії.

| Поле | Тип | Обов'язкове | Опис |
|---|---|---|---|
| `id` | bigint | так | номер користувача в нашій базі |
| `telegram_id` | bigint | так, **унікальне** | id користувача в Telegram (`message.from_user.id`) |
| `username` | varchar(64) | ні | `@username` — є не в усіх |
| `first_name` | varchar(128) | ні | ім'я з профілю Telegram |
| `created_at` | timestamptz | так | коли користувач з'явився в базі |

`id` і `telegram_id` — різні поля: так база не залежить від Telegram, якщо з'явиться інший спосіб входу (наприклад, авторизація в адмінці).

### cars — авто

Авто, які користувач пригнав, ремонтує або продає. Додаються кнопкою «🚗 Додати авто» або командою `/addcar`.

| Поле | Тип | Обов'язкове | Опис |
|---|---|---|---|
| `id` | bigint | так | номер авто |
| `user_id` | bigint | так | → `users.id`, хто веде облік цього авто |
| `brand` | varchar(50) | так | марка, напр. BMW |
| `model` | varchar(50) | так | модель, напр. X5 |
| `year` | smallint | так | рік випуску |
| `vin` | varchar(17) | ні, **унікальне** | VIN-код; може бути ще невідомий, але два авто з однаковим VIN бути не можуть |
| `created_at` | timestamptz | так | коли авто додали |

Статус «продано» окремо не зберігається: авто продане, якщо в нього є операція в категорії доходу «Продаж авто».

### categories — категорії операцій

Довідник, спільний для всіх користувачів. Заповнюють його міграції.

| Категорія | Тип |
|---|---|
| Купівля авто | витрата (`expense`) |
| Доставка | витрата |
| Розмитнення | витрата |
| Ремонт | витрата |
| Запчастини | витрата |
| Інше | витрата |
| Продаж авто | **дохід** (`income`) |

| Поле | Тип | Обов'язкове | Опис |
|---|---|---|---|
| `id` | integer | так | номер категорії |
| `name` | varchar(50) | так, **унікальне** | назва категорії |
| `type` | varchar(10) | так | `expense` — витрата, `income` — дохід; інших значень база не прийме |
| `created_at` | timestamptz | так | коли категорію додали |

Категорії — окрема таблиця, а не текст в операції: так не буде різнобою («ремонт», «Ремонт», «ремонт авто»), а суму по категорії легко порахувати. Тип операції (дохід чи витрата) визначає її категорія.

### transactions — фінансові операції

Кожна витрата чи продаж, які користувач записав у боті («💸 Додати витрату» / `/expense`, «💰 Продаж авто» / `/sell`).

| Поле | Тип | Обов'язкове | Опис |
|---|---|---|---|
| `id` | bigint | так | номер операції |
| `user_id` | bigint | так | → `users.id`, хто записав |
| `car_id` | bigint | ні | → `cars.id`, до якого авто належить; порожнє — загальна операція (бот зараз завжди просить обрати авто) |
| `category_id` | integer | так | → `categories.id`, категорія (а з нею — дохід чи витрата) |
| `operation_date` | date | так | **коли операція відбулася**; може бути раніше за `created_at` («заднім числом»), але не в майбутньому |
| `amount` | numeric(12, 2) | так | сума так, як її ввели, **завжди більше 0** |
| `currency` | varchar(3) | так | валюта введення: `UAH` або `USD` |
| `usd_rate` | numeric(10, 4) | так | офіційний курс НБУ (грн за $1) на `operation_date`, більше 0 |
| `amount_uah` | numeric(14, 2) | так | сума в гривнях за цим курсом |
| `amount_usd` | numeric(14, 2) | так | сума в доларах за цим курсом |
| `description` | text | ні | опис від користувача, напр. «заміна фар» |
| `created_at` | timestamptz | так | коли операцію записали в бота |

- Курс і суми в обох валютах **фіксуються в момент запису** й більше не змінюються. Підсумки рахуються з `amount_uah` і `amount_usd`.
- Гроші — `numeric`, а не `float`: рахуються точно, до копійки. Округлення до цілого — лише у відображенні (бот, адмінка).
- Правила на рівні бази (`CHECK`): `amount > 0`, `usd_rate > 0`, `currency in ('UAH', 'USD')`.
- Індекси: `(user_id, created_at)` — операції користувача; `operation_date` — сортування за датою операції.

## Зв'язки між таблицями

| Зв'язок | Тип | Що означає |
|---|---|---|
| `users` → `cars` | один до багатьох | один користувач веде облік багатьох авто; кожне авто має одного власника запису |
| `users` → `transactions` | один до багатьох | один користувач записує багато операцій; кожна операція — рівно одного користувача |
| `cars` → `transactions` | один до багатьох, **необов'язковий** | на одне авто — багато витрат і (після продажу) один дохід; операція може бути й без авто |
| `categories` → `transactions` | один до багатьох | в одній категорії багато операцій; кожна операція — рівно в одній категорії |

Зв'язки зроблені через зовнішні ключі (`FOREIGN KEY`): база не дасть записати операцію з неіснуючим користувачем, авто чи категорією.

**Калькуляція авто** (кожне авто — окремо, інші авто не враховуються):

- витрати = сума `amount_uah` (і `amount_usd`) операцій авто з категоріями типу `expense`;
- дохід = сума операцій авто з категорією типу `income` («Продаж авто»);
- прибуток = дохід − витрати (показується лише після продажу).

## Міграції

Структуру бази змінює лише [Alembic](https://alembic.sqlalchemy.org): кожна зміна — окремий файл у [migrations/versions/](../migrations/versions/), який лежить у Git.

| Міграція | Що робить |
|---|---|
| `0001_initial` | початкова схема: 4 таблиці й 6 категорій витрат |
| `0002_income_currency_date` | тип категорії й «Продаж авто»; у `transactions` — дата операції, валюта, курс НБУ, суми в грн і $. Наявні операції стали гривневими з датою запису й курсом НБУ на неї |

Команди (у Docker):

```powershell
docker compose run --rm migrate                          # застосувати всі нові міграції (alembic upgrade head)
docker compose run --rm migrate alembic current          # яка версія схеми в базі
docker compose run --rm migrate alembic history          # список міграцій
docker compose run --rm migrate alembic check            # чи збігаються моделі в коді з базою
```

`docker compose up` запускає `migrate` автоматично перед ботом і API.

Нова міграція після зміни `app/models.py`:

```powershell
docker compose run --rm migrate alembic revision --autogenerate -m "опис зміни"
```

Згенерований файл треба переглянути перед застосуванням — автогенерація не завжди правильно розуміє перейменування чи заповнення даних.

## Схема в коді (DBML)

Код для [dbdiagram.io](https://dbdiagram.io/d), з якого зроблено діаграму вище. Копіюйте **тільки вміст блоку** — без рядків із ` ``` `, інакше dbdiagram покаже помилку `Expect an identifier`.

```dbml
Project car_finance_bot {
  database_type: 'PostgreSQL'
  Note: 'Облік фінансових операцій під час пригону, ремонту та продажу авто: Telegram-бот + web-адмінка'
}

Table users {
  id bigint [pk, increment]
  telegram_id bigint [not null, unique, note: 'id користувача в Telegram (message.from_user.id)']
  username varchar(64) [note: '@username, може бути відсутній']
  first_name varchar(128)
  created_at timestamptz [not null, default: `now()`]

  Note: 'Користувачі Telegram, які надсилали боту операції'
}

Table cars {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id, note: 'власник запису — хто веде облік цього авто']
  brand varchar(50) [not null, note: 'марка, напр. BMW']
  model varchar(50) [not null, note: 'модель, напр. X5']
  year smallint [not null, note: 'рік випуску']
  vin varchar(17) [unique, note: 'VIN-код, 17 символів; може бути ще невідомий']
  created_at timestamptz [not null, default: `now()`]

  Note: 'Авто, які користувач пригнав, ремонтує або продає'
}

Table categories {
  id integer [pk, increment]
  name varchar(50) [not null, unique, note: 'Купівля авто, Доставка, Розмитнення, Ремонт, Запчастини, Інше, Продаж авто']
  type varchar(10) [not null, default: 'expense', note: 'expense — витрата, income — дохід']
  created_at timestamptz [not null, default: `now()`]

  Note: 'Довідник категорій, спільний для всіх користувачів'
}

Table transactions {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id, note: 'хто записав операцію']
  car_id bigint [ref: > cars.id, note: 'до якого авто належить; порожнє — загальна операція']
  category_id integer [not null, ref: > categories.id, note: 'категорія — визначає дохід чи витрата']
  operation_date date [not null, note: 'коли операція відбулася']
  amount numeric(12, 2) [not null, note: 'сума у валюті введення, завжди > 0']
  currency varchar(3) [not null, note: 'UAH або USD']
  usd_rate numeric(10, 4) [not null, note: 'курс НБУ, грн за $1, на operation_date']
  amount_uah numeric(14, 2) [not null, note: 'сума в гривнях']
  amount_usd numeric(14, 2) [not null, note: 'сума в доларах']
  description text [note: 'опис від користувача, напр. "заміна фар"']
  created_at timestamptz [not null, default: `now()`, note: 'коли записали в бота']

  indexes {
    (user_id, created_at) [name: 'ix_transactions_user_created']
    operation_date [name: 'ix_transactions_operation_date']
  }

  Note: 'Фінансові операції: витрати на авто й дохід від продажу'
}
```
