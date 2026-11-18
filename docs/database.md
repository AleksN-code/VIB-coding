# Схема бази даних

Схема бази даних бота для обліку витрат на пригін, ремонт і продаж авто. Перша версія: користувачі, авто, категорії, операції.

Це документація, а не сама база. Саму базу (Neon PostgreSQL) створює код бота через SQLAlchemy. Пояснення, чому схема саме така, — у [architecture.md](architecture.md#database).

**Як побачити діаграму:** скопіюйте вміст блоку нижче і вставте на [dbdiagram.io](https://dbdiagram.io/d).

```dbml
Project car_finance_bot {
  database_type: 'PostgreSQL'
  Note: 'Telegram-бот: облік фінансових операцій під час пригону, ремонту та продажу авто'
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
  name varchar(50) [not null, unique, note: 'Купівля авто, Доставка, Розмитнення, Ремонт, Запчастини, Інше']
  created_at timestamptz [not null, default: `now()`]

  Note: 'Довідник категорій витрат, спільний для всіх користувачів'
}

Table transactions {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id, note: 'хто записав операцію']
  car_id bigint [ref: > cars.id, note: 'до якого авто належить; порожнє — загальна витрата']
  category_id integer [not null, ref: > categories.id, note: 'до якої категорії належить']
  amount numeric(12, 2) [not null, note: 'сума, завжди > 0']
  description text [note: 'опис від користувача, напр. "заміна фар"']
  created_at timestamptz [not null, default: `now()`]

  indexes {
    (user_id, created_at) [name: 'ix_transactions_user_created']
  }

  Note: 'Фінансові операції користувачів'
}
```
