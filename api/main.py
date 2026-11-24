"""Backend API для web-адмінки.

Читає фінансові операції з Neon і віддає їх у JSON. React звертається тільки сюди,
до бази напряму не підключається: DATABASE_URL знає лише backend.

Документація й перевірка в браузері: http://localhost:8000/docs
"""

import asyncio
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

from api.car_images import find_car_image
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


class CarOut(BaseModel):
    id: int
    title: str
    brand: str
    model: str
    year: int
    vin: str | None
    sold: bool
    sale_date: date | None
    expenses: MoneyOut
    income: MoneyOut
    # Прибуток рахуємо лише після продажу: до того це просто вкладені гроші
    profit: MoneyOut | None
    transactions_count: int
    # Фото моделі з Вікіпедії (може бути відсутнім)
    image_url: str | None
    image_page_title: str | None
    image_page_url: str | None


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
    car_id: Annotated[int | None, Query(description="Лише операції цього авто")] = None,
) -> list[TransactionOut]:
    stmt = (
        select(Transaction, Category, Car)
        .join(Category, Category.id == Transaction.category_id)
        .outerjoin(Car, Car.id == Transaction.car_id)
        .order_by(Transaction.operation_date.desc(), Transaction.id.desc())
        .limit(limit)
    )
    if car_id is not None:
        stmt = stmt.where(Transaction.car_id == car_id)
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


@app.get(
    "/api/cars",
    response_model=list[CarOut],
    summary="Авто з окремою калькуляцією",
    description=(
        "Кожне авто — окремо: свої витрати, дохід від продажу і прибуток. "
        "Операції авто — GET /api/transactions?car_id=<id>."
    ),
)
async def list_cars() -> list[CarOut]:
    totals_stmt = (
        select(
            Transaction.car_id,
            Category.type,
            func.coalesce(func.sum(Transaction.amount_uah), 0),
            func.coalesce(func.sum(Transaction.amount_usd), 0),
            func.count(Transaction.id),
            func.max(Transaction.operation_date),
        )
        .join(Category, Category.id == Transaction.category_id)
        .where(Transaction.car_id.is_not(None))
        .group_by(Transaction.car_id, Category.type)
    )
    async with db.session_factory() as session:
        cars = (await session.scalars(select(Car).order_by(Car.id))).all()
        totals_rows = (await session.execute(totals_stmt)).all()

    # {car_id: {type: (uah, usd, count, last_date)}}
    totals: dict[int, dict[str, tuple]] = {}
    for car_id, type_, total_uah, total_usd, n, last_date in totals_rows:
        totals.setdefault(car_id, {})[type_] = (Decimal(total_uah), Decimal(total_usd), n, last_date)

    # Картинки з Вікіпедії — паралельно; кешуються, тож повільним буде лише перший запит
    images = await asyncio.gather(
        *(asyncio.to_thread(find_car_image, car.brand, car.model) for car in cars)
    )

    result = []
    for car, image in zip(cars, images):
        car_totals = totals.get(car.id, {})
        exp_uah, exp_usd, exp_n, _ = car_totals.get(EXPENSE, (Decimal(0), Decimal(0), 0, None))
        inc_uah, inc_usd, inc_n, sale_date = car_totals.get(INCOME, (Decimal(0), Decimal(0), 0, None))
        sold = inc_n > 0
        result.append(
            CarOut(
                id=car.id,
                title=f"{car.brand} {car.model} {car.year}",
                brand=car.brand,
                model=car.model,
                year=car.year,
                vin=car.vin,
                sold=sold,
                sale_date=sale_date,
                expenses=MoneyOut(uah=exp_uah, usd=exp_usd),
                income=MoneyOut(uah=inc_uah, usd=inc_usd),
                profit=MoneyOut(uah=inc_uah - exp_uah, usd=inc_usd - exp_usd) if sold else None,
                transactions_count=exp_n + inc_n,
                image_url=image.url if image else None,
                image_page_title=image.page_title if image else None,
                image_page_url=image.page_url if image else None,
            )
        )
    return result
