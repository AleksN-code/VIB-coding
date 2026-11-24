"""Операції з базою: користувачі, авто, категорії, витрати й доходи."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EXPENSE, Car, Category, Transaction, User
from app.nbu import to_uah_usd


async def get_or_create_user(
    session: AsyncSession, telegram_id: int, username: str | None, first_name: str | None
) -> User:
    """Повертає користувача за telegram_id; якщо його ще немає — створює.

    Username та ім'я оновлюються, якщо користувач змінив їх у Telegram.
    """
    stmt = (
        insert(User)
        .values(telegram_id=telegram_id, username=username, first_name=first_name)
        .on_conflict_do_update(
            index_elements=["telegram_id"],
            set_={"username": username, "first_name": first_name},
        )
        .returning(User)
        # оновити об'єкт свіжими даними з бази, навіть якщо він уже є в сесії
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(stmt)).one()


async def add_car(
    session: AsyncSession, user_id: int, brand: str, model: str, year: int, vin: str | None
) -> Car:
    car = Car(user_id=user_id, brand=brand, model=model, year=year, vin=vin)
    session.add(car)
    await session.flush()  # отримати car.id до commit
    return car


async def list_cars(session: AsyncSession, user_id: int) -> list[Car]:
    stmt = select(Car).where(Car.user_id == user_id).order_by(Car.id)
    return list(await session.scalars(stmt))


async def get_user_car(session: AsyncSession, user_id: int, car_id: int) -> Car | None:
    """Авто, тільки якщо воно належить цьому користувачу."""
    stmt = select(Car).where(Car.id == car_id, Car.user_id == user_id)
    return await session.scalar(stmt)


async def list_categories(session: AsyncSession, type_: str) -> list[Category]:
    """Категорії одного типу: EXPENSE (витрати) або INCOME (доходи)."""
    stmt = select(Category).where(Category.type == type_).order_by(Category.id)
    return list(await session.scalars(stmt))


async def get_category(session: AsyncSession, category_id: int) -> Category | None:
    return await session.get(Category, category_id)


async def add_transaction(
    session: AsyncSession,
    user_id: int,
    car_id: int,
    category_id: int,
    operation_date: date,
    amount: Decimal,
    currency: str,
    usd_rate: Decimal,
    description: str | None,
) -> Transaction:
    """Записує операцію. Суму в другій валюті рахує за курсом НБУ `usd_rate` і фіксує назавжди."""
    amount_uah, amount_usd = to_uah_usd(amount, currency, usd_rate)
    transaction = Transaction(
        user_id=user_id,
        car_id=car_id,
        category_id=category_id,
        operation_date=operation_date,
        amount=amount,
        currency=currency,
        usd_rate=usd_rate,
        amount_uah=amount_uah,
        amount_usd=amount_usd,
        description=description,
    )
    session.add(transaction)
    await session.flush()
    return transaction


async def car_expenses_uah(session: AsyncSession, car_id: int) -> Decimal:
    """Скільки всього витрачено на авто, у гривнях."""
    stmt = (
        select(func.coalesce(func.sum(Transaction.amount_uah), 0))
        .join(Category, Category.id == Transaction.category_id)
        .where(Transaction.car_id == car_id, Category.type == EXPENSE)
    )
    return Decimal(await session.scalar(stmt))
