"""Backend API для web-адмінки.

Читає фінансові операції з Neon і віддає їх у JSON. React звертається тільки сюди,
до бази напряму не підключається: DATABASE_URL знає лише backend.

Документація й перевірка в браузері: http://localhost:8000/docs
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, PlainSerializer
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import EXPENSE, INCOME, Car, Category, Transaction

load_dotenv()

logger = logging.getLogger("api")

# Гроші в JSON — числами (1149000.0), а не рядками, щоб frontend одразу міг їх показати.
# У базі вони точні (numeric), округлення до цілого — на боці frontend.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


@asynccontextmanager
async def lifespan(_: FastAPI):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Не задано DATABASE_URL. Додайте його у файл .env (див. .env.example).")
    db.setup_engine(database_url)
    await db.check_db()
    yield
    await db.close_db()


app = FastAPI(
    title="Car Finance — Admin API",
    description="Read-only API для web-адмінки: фінансові операції по авто з бази Neon PostgreSQL.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(SQLAlchemyError)
async def database_error(_: Request, error: SQLAlchemyError) -> JSONResponse:
    """База недоступна чи запит упав — відповідаємо JSON, а не HTML-сторінкою помилки."""
    logger.error("Помилка бази даних: %s", type(error).__name__)
    return JSONResponse(status_code=503, content={"detail": "База даних тимчасово недоступна"})


# ---------- Схеми відповідей ----------


class TransactionOut(BaseModel):
    id: int
    date: date
    type: Literal["income", "expense"]
    car: str | None
    category: str
    # Сума так, як її ввели в боті, і валюта введення
    amount: Money
    currency: Literal["UAH", "USD"]
    # Курс НБУ на дату операції і суми в обох валютах за ним
    usd_rate: Money
    amount_uah: Money
    amount_usd: Money
    description: str | None
    created_at: datetime


class MoneyOut(BaseModel):
    uah: Money
    usd: Money


class SummaryOut(BaseModel):
    total_income: MoneyOut
    total_expense: MoneyOut
    balance: MoneyOut
    transactions_count: int


# ---------- Endpoint-и ----------


@app.get("/api/health", summary="Чи працює API і чи доступна база")
async def health() -> dict:
    await db.check_db()
    return {"status": "ok"}


@app.get(
    "/api/transactions",
    response_model=list[TransactionOut],
    summary="Список фінансових операцій",
    description="Нові зверху (за датою операції). Типи: income — дохід (продаж авто), expense — витрата.",
)
async def list_transactions(
    limit: Annotated[int, Query(ge=1, le=500, description="Скільки операцій повернути")] = 100,
) -> list[TransactionOut]:
    stmt = (
        select(Transaction, Category, Car)
        .join(Category, Category.id == Transaction.category_id)
        .outerjoin(Car, Car.id == Transaction.car_id)
        .order_by(Transaction.operation_date.desc(), Transaction.id.desc())
        .limit(limit)
    )
    async with db.session_factory() as session:
        rows = (await session.execute(stmt)).all()

    return [
        TransactionOut(
            id=t.id,
            date=t.operation_date,
            type=category.type,
            car=f"{car.brand} {car.model} {car.year}" if car else None,
            category=category.name,
            amount=t.amount,
            currency=t.currency,
            usd_rate=t.usd_rate,
            amount_uah=t.amount_uah,
            amount_usd=t.amount_usd,
            description=t.description,
            created_at=t.created_at,
        )
        for t, category, car in rows
    ]


@app.get(
    "/api/summary",
    response_model=SummaryOut,
    summary="Фінансове зведення",
    description="Доходи, витрати й баланс (доходи − витрати) у гривнях і доларах за всіма операціями.",
)
async def summary() -> SummaryOut:
    stmt = (
        select(
            Category.type,
            func.coalesce(func.sum(Transaction.amount_uah), 0),
            func.coalesce(func.sum(Transaction.amount_usd), 0),
            func.count(Transaction.id),
        )
        .join(Category, Category.id == Transaction.category_id)
        .group_by(Category.type)
    )
    async with db.session_factory() as session:
        rows = (await session.execute(stmt)).all()

    totals = {INCOME: (Decimal(0), Decimal(0)), EXPENSE: (Decimal(0), Decimal(0))}
    count = 0
    for type_, total_uah, total_usd, n in rows:
        totals[type_] = (Decimal(total_uah), Decimal(total_usd))
        count += n

    income_uah, income_usd = totals[INCOME]
    expense_uah, expense_usd = totals[EXPENSE]
    return SummaryOut(
        total_income=MoneyOut(uah=income_uah, usd=income_usd),
        total_expense=MoneyOut(uah=expense_uah, usd=expense_usd),
        balance=MoneyOut(uah=income_uah - expense_uah, usd=income_usd - expense_usd),
        transactions_count=count,
    )
