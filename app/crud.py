"""Операції з базою: користувачі, авто, категорії, витрати й доходи."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EXPENSE, INCOME, Car, Category, Transaction, User
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


async def get_user_car(
    session: AsyncSession, user_id: int, car_id: int, lock: bool = False
) -> Car | None:
    """Авто, тільки якщо воно належить цьому користувачу.

    lock=True блокує рядок авто до кінця транзакції — щоб два одночасні продажі
    одного авто не записалися обидва.
    """
    stmt = select(Car).where(Car.id == car_id, Car.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def list_categories(session: AsyncSession, type_: str) -> list[Category]:
    """Категорії одного типу: EXPENSE (витрати) або INCOME (доходи)."""
    stmt = select(Category).where(Category.type == type_).order_by(Category.id)
    return list(await session.scalars(stmt))


async def get_category(session: AsyncSession, category_id: int) -> Category | None:
    return await session.get(Category, category_id)


async def get_category_by_name(session: AsyncSession, name: str) -> Category | None:
    return await session.scalar(select(Category).where(Category.name == name))


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


@dataclass
class CarSummary:
    """Калькуляція одного авто: витрати, дохід від продажу і прибуток."""

    expenses_uah: Decimal = Decimal(0)
    expenses_usd: Decimal = Decimal(0)
    income_uah: Decimal = Decimal(0)
    income_usd: Decimal = Decimal(0)
    sale_date: date | None = None

    @property
    def sold(self) -> bool:
        return self.sale_date is not None

    @property
    def profit_uah(self) -> Decimal:
        return self.income_uah - self.expenses_uah

    @property
    def profit_usd(self) -> Decimal:
        # Кожна операція перерахована за курсом на свою дату, тому прибуток у $ —
        # різниця сум у $, а не прибуток у грн, поділений на сьогоднішній курс
        return self.income_usd - self.expenses_usd


async def car_summary(session: AsyncSession, car_id: int) -> CarSummary:
    """Витрати й доходи одного авто. Інші авто не враховуються."""
    stmt = (
        select(
            Category.type,
            func.coalesce(func.sum(Transaction.amount_uah), 0),
            func.coalesce(func.sum(Transaction.amount_usd), 0),
            func.max(Transaction.operation_date),
        )
        .join(Category, Category.id == Transaction.category_id)
        .where(Transaction.car_id == car_id)
        .group_by(Category.type)
    )
    summary = CarSummary()
    for type_, total_uah, total_usd, last_date in await session.execute(stmt):
        if type_ == EXPENSE:
            summary.expenses_uah, summary.expenses_usd = Decimal(total_uah), Decimal(total_usd)
        elif type_ == INCOME:
            summary.income_uah, summary.income_usd = Decimal(total_uah), Decimal(total_usd)
            summary.sale_date = last_date
    return summary
