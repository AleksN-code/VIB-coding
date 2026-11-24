"""Таблиці бази даних як класи SQLAlchemy.

Схема й пояснення — у docs/database.md і docs/architecture.md.
Зміни структури бази — тільки через міграції Alembic (папка migrations/).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Тип категорії
EXPENSE = "expense"
INCOME = "income"

# Категорія доходу від продажу авто (створюється міграцією 0002)
SALE_CATEGORY = "Продаж авто"

# Валюти, в яких можна ввести суму
CURRENCIES = ("UAH", "USD")


class Base(DeclarativeBase):
    """Базовий клас: SQLAlchemy збирає в ньому всі таблиці."""


class User(Base):
    """Користувач Telegram."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Car(Base):
    """Авто, яке користувач пригнав, ремонтує або продає."""

    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    brand: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(50))
    year: Mapped[int] = mapped_column(SmallInteger)
    vin: Mapped[str | None] = mapped_column(String(17), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Category(Base):
    """Категорія операцій, спільна для всіх користувачів: витрата або дохід."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("type in ('income', 'expense')", name="ck_categories_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    type: Mapped[str] = mapped_column(String(10), server_default=EXPENSE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Transaction(Base):
    """Фінансова операція: витрата на авто або дохід від його продажу."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("currency in ('UAH', 'USD')", name="ck_transactions_currency"),
        CheckConstraint("usd_rate > 0", name="ck_transactions_usd_rate_positive"),
        Index("ix_transactions_user_created", "user_id", "created_at"),
        Index("ix_transactions_operation_date", "operation_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # Порожнє — загальна операція, не прив'язана до авто
    car_id: Mapped[int | None] = mapped_column(ForeignKey("cars.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    # Коли операція відбулася (created_at — коли її записали в бота)
    operation_date: Mapped[date] = mapped_column(Date)
    # Сума так, як її ввів користувач, і валюта введення
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    # Офіційний курс НБУ (грн за $1) на дату операції — фіксується назавжди
    usd_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    # Сума в обох валютах за цим курсом
    amount_uah: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
