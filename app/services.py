"""Дії з авто й операціями — спільні для Telegram-бота і web-адмінки.

Будь-яка зміна проходить однаковий шлях, звідки б вона не прийшла:

    перевірка даних (app/rules.py)
    → правила обліку (продаж лише один, тип операції не змінюється)
    → курс НБУ на дату операції
    → запис через SQLAlchemy (app/crud.py) у Neon

Помилки — з app/errors.py, з текстом для людини.

owner_id: бот передає id користувача — він може змінювати лише свої авто й операції;
web-адмінка передає None — вона бачить усі авто.

commit робить той, хто викликає (бот або API): так дія й відповідь користувачу
бачать ту саму транзакцію бази.
"""

import asyncio
import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, nbu, rules
from app.errors import ConflictError, NotFoundError, RateUnavailableError, ValidationError
from app.models import INCOME, Car, Category, Transaction

logger = logging.getLogger(__name__)

ALREADY_SOLD = "Це авто вже продано — другий продаж не записано."


# ---------- Допоміжні ----------


async def usd_rate_on(day: date) -> Decimal:
    """Курс НБУ на дату. Запит до сайту НБУ — в окремому потоці, щоб не зупиняти бота й API."""
    try:
        return await asyncio.to_thread(nbu.get_usd_rate, day)
    except nbu.NbuRateError as error:
        logger.warning("Курс НБУ недоступний: %s", error)
        raise RateUnavailableError(
            "Не вдалося отримати офіційний курс долара НБУ, тому операцію не збережено. "
            "Спробуйте ще раз за хвилину."
        ) from error


async def _car(session: AsyncSession, car_id: int, owner_id: int | None, lock: bool = False) -> Car:
    car = await crud.get_car(session, car_id, owner_id, lock=lock)
    if car is None:
        raise NotFoundError("Авто не знайдено.")
    return car


async def _category(session: AsyncSession, category_id: int) -> Category:
    category = await crud.get_category(session, category_id)
    if category is None:
        raise NotFoundError("Категорію не знайдено.")
    return category


async def _transaction(session: AsyncSession, transaction_id: int, owner_id: int | None) -> Transaction:
    transaction = await crud.get_transaction(session, transaction_id, owner_id)
    if transaction is None:
        raise NotFoundError("Операцію не знайдено.")
    return transaction


async def _save_car(session: AsyncSession, car: Car, **fields) -> None:
    """Записує поля авто. VIN унікальний — якщо такий уже є, повертаємо зрозумілу помилку."""
    try:
        # Точка відкату (SAVEPOINT): помилка VIN скасовує лише цей запис, а не всю сесію.
        # Поля змінюємо всередині неї — інакше SQLAlchemy записав би їх ще до точки відкату.
        async with session.begin_nested():
            for name, value in fields.items():
                setattr(car, name, value)
            session.add(car)
            await session.flush()
    except IntegrityError as error:
        raise ConflictError(f"Авто з VIN {fields.get('vin')} уже є в базі.") from error


# ---------- Авто ----------


async def create_car(
    session: AsyncSession, owner_id: int, brand: str, model: str, year: int, vin: str | None
) -> Car:
    """Нове авто користувача owner_id."""
    brand, model, year, vin = rules.check_car(brand, model, year, vin)
    car = Car(user_id=owner_id)
    await _save_car(session, car, brand=brand, model=model, year=year, vin=vin)
    return car


async def update_car(
    session: AsyncSession,
    car_id: int,
    brand: str,
    model: str,
    year: int,
    vin: str | None,
    owner_id: int | None = None,
) -> Car:
    """Змінює марку, модель, рік і VIN. Операції авто не змінюються."""
    brand, model, year, vin = rules.check_car(brand, model, year, vin)
    car = await _car(session, car_id, owner_id, lock=True)
    await _save_car(session, car, brand=brand, model=model, year=year, vin=vin)
    return car


async def delete_car(session: AsyncSession, car_id: int, owner_id: int | None = None) -> int:
    """Видаляє авто разом з усіма його операціями. Повертає, скільки операцій видалено.

    Перед викликом бот і сайт показують попередження з кількістю операцій
    (crud.count_car_transactions).
    """
    car = await _car(session, car_id, owner_id, lock=True)
    result = await session.execute(delete(Transaction).where(Transaction.car_id == car.id))
    await session.delete(car)
    await session.flush()
    return result.rowcount


# ---------- Операції ----------


async def create_transaction(
    session: AsyncSession,
    *,
    car_id: int,
    category_id: int,
    operation_date: date,
    amount: Decimal,
    currency: str,
    description: str | None,
    owner_id: int | None = None,
) -> Transaction:
    """Нова операція: витрата або продаж — залежно від типу категорії.

    Курс НБУ на дату операції фіксується назавжди, суми в гривнях і доларах — теж.
    """
    amount = rules.check_amount(amount)
    currency = rules.check_currency(currency)
    operation_date = rules.check_operation_date(operation_date)
    description = rules.check_description(description)

    # Курс — до запитів у базу: сайт НБУ може відповідати кілька секунд
    usd_rate = await usd_rate_on(operation_date)

    category = await _category(session, category_id)
    # lock=True: поки записуємо, інший продаж цього авто чекає
    car = await _car(session, car_id, owner_id, lock=True)
    if category.type == INCOME and await crud.car_is_sold(session, car.id):
        raise ConflictError(ALREADY_SOLD)

    # Операція належить власнику авто — і коли її записали в боті, і на сайті
    return await crud.add_transaction(
        session, car.user_id, car.id, category.id,
        operation_date, amount, currency, usd_rate, description,
    )


async def update_transaction(
    session: AsyncSession,
    transaction_id: int,
    *,
    car_id: int,
    category_id: int,
    operation_date: date,
    amount: Decimal,
    currency: str,
    description: str | None,
    owner_id: int | None = None,
) -> Transaction:
    """Змінює операцію. Передаються всі поля — і змінені, і ті, що лишаються як були.

    - Тип не змінюється: витрата лишається витратою, продаж — продажем.
    - Нова дата → новий курс НБУ на цю дату. Та сама дата → курс лишається, перераховуються
      лише суми (якщо змінили суму чи валюту).
    - Продаж можна перенести на інше авто, лише якщо те ще не продане.
    """
    amount = rules.check_amount(amount)
    currency = rules.check_currency(currency)
    operation_date = rules.check_operation_date(operation_date)
    description = rules.check_description(description)

    transaction = await _transaction(session, transaction_id, owner_id)
    if operation_date == transaction.operation_date:
        usd_rate = transaction.usd_rate
    else:
        usd_rate = await usd_rate_on(operation_date)

    old_category = await _category(session, transaction.category_id)
    category = await _category(session, category_id)
    if category.type != old_category.type:
        raise ValidationError(
            "Тип операції змінити не можна: витрата лишається витратою, продаж — продажем. "
            "Видаліть операцію і створіть нову."
        )

    car = await _car(session, car_id, owner_id, lock=True)
    if category.type == INCOME and await crud.car_is_sold(
        session, car.id, exclude_transaction_id=transaction.id
    ):
        raise ConflictError("Це авто вже продано — на нього не можна перенести ще один продаж.")

    amount_uah, amount_usd = nbu.to_uah_usd(amount, currency, usd_rate)
    transaction.user_id = car.user_id
    transaction.car_id = car.id
    transaction.category_id = category.id
    transaction.operation_date = operation_date
    transaction.amount = amount
    transaction.currency = currency
    transaction.usd_rate = usd_rate
    transaction.amount_uah = amount_uah
    transaction.amount_usd = amount_usd
    transaction.description = description
    await session.flush()
    return transaction


async def delete_transaction(
    session: AsyncSession, transaction_id: int, owner_id: int | None = None
) -> Transaction:
    """Видаляє операцію. Якщо це був продаж — авто знову стає непроданим.

    Повертає видалену операцію, щоб показати, що саме видалено.
    """
    transaction = await _transaction(session, transaction_id, owner_id)
    await session.delete(transaction)
    await session.flush()
    return transaction
