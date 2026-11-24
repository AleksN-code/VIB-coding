"""Backend API для web-адмінки.

Показує фінансові операції з Neon і змінює їх. React звертається тільки сюди,
до бази напряму не підключається: DATABASE_URL знає лише backend.

Будь-яка зміна проходить ланцюг:
    React-форма → цей API → перевірка (app/rules.py, app/services.py) → SQLAlchemy → Neon
Ту саму перевірку й логіку використовує Telegram-бот.

Доступ — лише після входу паролем ADMIN_PASSWORD (api/auth.py): без сесії кожен /api/...
(крім /api/health, /api/login, /api/logout) відповідає 401. Це базовий навчальний захист,
тому API однаково доступний лише на цьому ПК (127.0.0.1).

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
from fastapi import FastAPI, Path, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, PlainSerializer
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api import auth
from api.car_images import find_car_image
from app import db, services
from app.errors import AppError, ConflictError, NotFoundError, RateUnavailableError, ValidationError
from app.models import EXPENSE, INCOME, Car, Category, Transaction, User

load_dotenv()

# Записи API (хто що створив, змінив, видалив) — у логи контейнера: docker compose logs api
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
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
    # Пароль адмінки — лише з .env; якщо його немає, вхід закрито для всіх
    auth.configure(os.getenv("ADMIN_PASSWORD"))
    yield
    await db.close_db()


app = FastAPI(
    title="Car Finance — Admin API",
    description=(
        "API для web-адмінки: перегляд і керування фінансовими операціями по авто "
        "в базі Neon PostgreSQL. Помилки — JSON з текстом для людини: {\"detail\": \"...\"}."
    ),
    version="0.2.0",
    lifespan=lifespan,
)


# ---------- Помилки: завжди JSON з поясненням українською ----------

# Помилки спільної логіки (app/errors.py) → HTTP-статус
ERROR_STATUS = {
    ValidationError: 422,  # неправильні дані
    NotFoundError: 404,  # немає такого авто / операції / категорії
    ConflictError: 409,  # суперечить записаному: другий продаж авто
    RateUnavailableError: 503,  # сайт НБУ не відповів
}

# Якщо дані не пройшли навіть перевірку формату (не число, не та дата, поле відсутнє)
FIELD_ERRORS = {
    "body": "Надішліть дані операції у форматі JSON.",
    "car_id": "Оберіть авто.",
    "type": "Тип операції має бути income (дохід) або expense (витрата).",
    "category_id": "Оберіть категорію.",
    "date": "Вкажіть дату операції у форматі РРРР-ММ-ДД.",
    "amount": "Сума має бути числом, більшим за 0.",
    "currency": "Валюта має бути UAH (гривня) або USD (долар).",
    "description": "Опис має бути текстом.",
    "owner_id": "Оберіть власника авто.",
    "brand": "Вкажіть марку авто.",
    "model": "Вкажіть модель авто.",
    "year": "Рік випуску має бути числом, наприклад 2018.",
    "vin": "VIN має бути текстом.",
    "limit": "limit — ціле число від 1 до 500.",
    "password": "Введіть пароль.",
}


# ---------- Захист: без входу — лише /api/health ----------

# Адреси, доступні без входу. Усі інші /api/... — тільки з дійсною сесією,
# тож нові endpoint-и захищені автоматично, навіть якщо про це забути.
PUBLIC_PATHS = {"/api/health", "/api/login", "/api/logout"}


@app.middleware("http")
async def require_admin_session(request: Request, call_next):
    path = request.url.path
    if (
        path.startswith("/api/")
        and path not in PUBLIC_PATHS
        and not auth.session_valid(request.cookies.get(auth.COOKIE_NAME))
    ):
        return JSONResponse(status_code=401, content={"detail": "Потрібно увійти в адмінку."})
    return await call_next(request)


@app.exception_handler(AppError)
async def app_error(_: Request, error: AppError) -> JSONResponse:
    """Дію не виконано через дані чи правила обліку — пояснюємо чому."""
    status_code = next(
        (code for error_class, code in ERROR_STATUS.items() if isinstance(error, error_class)), 400
    )
    return JSONResponse(status_code=status_code, content={"detail": error.message})


@app.exception_handler(RequestValidationError)
async def request_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    """Замість технічного списку помилок FastAPI — коротке пояснення по кожному полю."""
    messages = []
    for item in error.errors():
        field = str(item["loc"][-1]) if item["loc"] else "body"
        if item["loc"] and item["loc"][0] == "path":
            # /api/transactions/abc, /api/cars/abc
            message = "Номер в адресі запиту має бути цілим числом."
        else:
            message = FIELD_ERRORS.get(field, f"Неправильне значення поля {field}.")
        if message not in messages:
            messages.append(message)
    return JSONResponse(
        status_code=422,
        # errors — технічні подробиці для розробника (видно в /docs і в DevTools)
        content={"detail": " ".join(messages), "errors": jsonable_encoder(error.errors())},
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
    car_id: int | None
    car: str | None
    category_id: int
    category: str
    # Сума так, як її ввели (у боті чи на сайті), і валюта введення
    amount: Money
    currency: Literal["UAH", "USD"]
    # Курс НБУ на дату операції і суми в обох валютах за ним
    usd_rate: Money
    amount_uah: Money
    amount_usd: Money
    description: str | None
    created_at: datetime


class TransactionIn(BaseModel):
    """Дані з форми операції — для створення і для зміни."""

    car_id: int = Field(description="Авто, до якого належить операція")
    type: Literal["income", "expense"] = Field(description="income — дохід (продаж), expense — витрата")
    category_id: int = Field(description="Категорія того ж типу — див. GET /api/categories")
    # Annotated, а не «= Field(...)»: поле й тип мають однакову назву date
    date: Annotated[date, Field(description="Дата операції; не в майбутньому")]
    amount: Decimal = Field(description="Сума більше 0, до 2 знаків після коми", examples=[450])
    currency: Literal["UAH", "USD"] = Field(description="Валюта, в якій введено суму")
    description: str | None = Field(default=None, description="Опис, до 500 символів")


class CategoryOut(BaseModel):
    id: int
    name: str
    type: Literal["income", "expense"]


class MoneyOut(BaseModel):
    uah: Money
    usd: Money


class SummaryOut(BaseModel):
    total_income: MoneyOut
    total_expense: MoneyOut
    balance: MoneyOut
    transactions_count: int


class UserOut(BaseModel):
    """Користувач Telegram-бота — власник авто."""

    id: int
    name: str


class CarIn(BaseModel):
    """Дані з форми авто — для створення і для зміни."""

    owner_id: int = Field(description="Власник — користувач бота, див. GET /api/users")
    brand: str = Field(description="Марка, до 50 символів", examples=["BMW"])
    model: str = Field(description="Модель, до 50 символів", examples=["X5"])
    year: int = Field(description="Рік випуску", examples=[2018])
    vin: str | None = Field(default=None, description="Необов'язково: 17 символів, без I, O, Q")


class CarSavedOut(BaseModel):
    """Авто після створення чи зміни. Повну картку з сумами дає GET /api/cars."""

    id: int
    title: str
    brand: str
    model: str
    year: int
    vin: str | None
    owner_id: int
    owner: str


class CarOut(BaseModel):
    id: int
    title: str
    brand: str
    model: str
    year: int
    vin: str | None
    owner_id: int
    owner: str
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


@app.get("/api/health", summary="Чи працює API і чи доступна база (без входу)")
async def health() -> dict:
    await db.check_db()
    return {"status": "ok"}


class LoginIn(BaseModel):
    password: str = Field(description="Пароль адмінки — значення ADMIN_PASSWORD з .env")


@app.post(
    "/api/login",
    status_code=204,
    summary="Вхід в адмінку",
    description="Правильний пароль — сесія в cookie (HttpOnly) на 12 годин.",
    responses={
        401: {"description": "Неправильний пароль"},
        429: {"description": "Забагато невдалих спроб — зачекайте хвилину"},
        503: {"description": "ADMIN_PASSWORD не задано в .env"},
    },
)
async def login(body: LoginIn) -> Response:
    if auth.problem():
        return JSONResponse(status_code=503, content={"detail": auth.problem()})
    if auth.too_many_attempts():
        return JSONResponse(
            status_code=429, content={"detail": "Забагато невдалих спроб. Зачекайте хвилину й спробуйте ще раз."}
        )
    if not auth.check_password(body.password):
        await asyncio.sleep(1)  # уповільнюємо підбір пароля
        return JSONResponse(status_code=401, content={"detail": "Неправильний пароль."})

    response = Response(status_code=204)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.new_session(),
        max_age=auth.SESSION_SECONDS,
        httponly=True,  # JavaScript сторінки cookie не бачить
        samesite="strict",  # інші сайти не можуть надіслати запит з цим cookie
        path="/api",
        # secure=True — коли адмінка працюватиме через HTTPS (наприклад, на Render)
    )
    logger.info("Вхід в адмінку")
    return response


@app.post("/api/logout", status_code=204, summary="Вийти з адмінки")
async def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(auth.COOKIE_NAME, path="/api", httponly=True, samesite="strict")
    return response


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

    return [transaction_out(t, category, car) for t, category, car in rows]


def transaction_out(t: Transaction, category: Category, car: Car | None) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        date=t.operation_date,
        type=category.type,
        car_id=t.car_id,
        car=f"{car.brand} {car.model} {car.year}" if car else None,
        category_id=t.category_id,
        category=category.name,
        amount=t.amount,
        currency=t.currency,
        usd_rate=t.usd_rate,
        amount_uah=t.amount_uah,
        amount_usd=t.amount_usd,
        description=t.description,
        created_at=t.created_at,
    )


async def saved_transaction_out(session: AsyncSession, t: Transaction) -> TransactionOut:
    """Операція після запису — з назвою категорії й авто, як у списку."""
    await session.refresh(t)  # created_at ставить база — читаємо його звідти
    category = await session.get(Category, t.category_id)
    car = await session.get(Car, t.car_id) if t.car_id else None
    return transaction_out(t, category, car)


ERROR_RESPONSES = {
    404: {"description": "Авто, операцію чи категорію не знайдено"},
    409: {"description": "Суперечить записаному: авто вже продано"},
    422: {"description": "Неправильні дані: сума, дата, тип, категорія"},
    503: {"description": "Немає курсу НБУ або база недоступна"},
}


@app.post(
    "/api/transactions",
    response_model=TransactionOut,
    status_code=201,
    summary="Створити операцію",
    description=(
        "Перевіряє дані, бере курс НБУ на дату операції і зберігає операцію. "
        "Дохід (продаж) — лише один на авто."
    ),
    responses=ERROR_RESPONSES,
)
async def create_transaction(body: TransactionIn) -> TransactionOut:
    async with db.session_factory() as session:
        t = await services.create_transaction(
            session,
            car_id=body.car_id,
            category_id=body.category_id,
            operation_date=body.date,
            amount=body.amount,
            currency=body.currency,
            description=body.description,
            type_=body.type,
        )
        await session.commit()
        result = await saved_transaction_out(session, t)
    logger.info("Створено операцію id=%s (%s) car_id=%s", t.id, body.type, t.car_id)
    return result


@app.put(
    "/api/transactions/{transaction_id}",
    response_model=TransactionOut,
    summary="Змінити операцію",
    description=(
        "Передаються всі поля форми. Тип змінити не можна. Нова дата — новий курс НБУ; "
        "та сама дата — курс лишається, перераховуються суми."
    ),
    responses=ERROR_RESPONSES,
)
async def update_transaction(
    transaction_id: Annotated[int, Path(description="Номер операції")], body: TransactionIn
) -> TransactionOut:
    async with db.session_factory() as session:
        t = await services.update_transaction(
            session,
            transaction_id,
            car_id=body.car_id,
            category_id=body.category_id,
            operation_date=body.date,
            amount=body.amount,
            currency=body.currency,
            description=body.description,
            type_=body.type,
        )
        await session.commit()
        result = await saved_transaction_out(session, t)
    logger.info("Змінено операцію id=%s", transaction_id)
    return result


@app.delete(
    "/api/transactions/{transaction_id}",
    status_code=204,
    summary="Видалити операцію",
    description="Назавжди. Якщо це продаж — авто знову стає непроданим.",
    responses={404: ERROR_RESPONSES[404]},
)
async def delete_transaction(
    transaction_id: Annotated[int, Path(description="Номер операції")],
) -> Response:
    async with db.session_factory() as session:
        await services.delete_transaction(session, transaction_id)
        await session.commit()
    logger.info("Видалено операцію id=%s", transaction_id)
    return Response(status_code=204)


@app.get(
    "/api/categories",
    response_model=list[CategoryOut],
    summary="Категорії операцій",
    description="Для форми: expense — витрати, income — доходи (продаж авто).",
)
async def list_categories() -> list[CategoryOut]:
    async with db.session_factory() as session:
        categories = (await session.scalars(select(Category).order_by(Category.id))).all()
    return [CategoryOut(id=c.id, name=c.name, type=c.type) for c in categories]


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
        cars_rows = (
            await session.execute(select(Car, User).join(User, User.id == Car.user_id).order_by(Car.id))
        ).all()
        totals_rows = (await session.execute(totals_stmt)).all()
    cars = [car for car, _ in cars_rows]
    owners = {car.id: user for car, user in cars_rows}

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
                owner_id=car.user_id,
                owner=user_name(owners[car.id]),
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


# ---------- Власники й авто ----------


def user_name(user: User) -> str:
    """Як показувати власника: ім'я з Telegram і @username."""
    name = user.first_name or "Без імені"
    return f"{name} (@{user.username})" if user.username else name


def car_saved_out(car: Car, owner: User) -> CarSavedOut:
    return CarSavedOut(
        id=car.id,
        title=f"{car.brand} {car.model} {car.year}",
        brand=car.brand,
        model=car.model,
        year=car.year,
        vin=car.vin,
        owner_id=car.user_id,
        owner=user_name(owner),
    )


CAR_ERROR_RESPONSES = {
    404: {"description": "Авто чи власника не знайдено"},
    409: {"description": "Авто з таким VIN уже є"},
    422: {"description": "Неправильні дані: марка, модель, рік, VIN"},
}


@app.get(
    "/api/users",
    response_model=list[UserOut],
    summary="Користувачі бота — власники авто",
    description="Для поля «Власник» у формі авто.",
)
async def list_users() -> list[UserOut]:
    async with db.session_factory() as session:
        users = (await session.scalars(select(User).order_by(User.id))).all()
    return [UserOut(id=u.id, name=user_name(u)) for u in users]


@app.post(
    "/api/cars",
    response_model=CarSavedOut,
    status_code=201,
    summary="Додати авто",
    description="Власник бачитиме це авто і в Telegram-боті.",
    responses=CAR_ERROR_RESPONSES,
)
async def create_car(body: CarIn) -> CarSavedOut:
    async with db.session_factory() as session:
        car = await services.create_car(session, body.owner_id, body.brand, body.model, body.year, body.vin)
        await session.commit()
        owner = await session.get(User, car.user_id)
    logger.info("Додано авто id=%s власник user_id=%s", car.id, car.user_id)
    return car_saved_out(car, owner)


@app.put(
    "/api/cars/{car_id}",
    response_model=CarSavedOut,
    summary="Змінити авто",
    description=(
        "Марка, модель, рік, VIN і власник. Якщо змінити власника — операції авто "
        "переходять до нього разом з авто."
    ),
    responses=CAR_ERROR_RESPONSES,
)
async def update_car(car_id: Annotated[int, Path(description="Номер авто")], body: CarIn) -> CarSavedOut:
    async with db.session_factory() as session:
        car = await services.update_car(
            session, car_id, body.brand, body.model, body.year, body.vin, new_owner_id=body.owner_id
        )
        await session.commit()
        owner = await session.get(User, car.user_id)
    logger.info("Змінено авто id=%s", car_id)
    return car_saved_out(car, owner)


@app.delete(
    "/api/cars/{car_id}",
    status_code=204,
    summary="Видалити авто",
    description="Назавжди, разом з усіма операціями авто (витрати й продаж).",
    responses={404: CAR_ERROR_RESPONSES[404]},
)
async def delete_car(car_id: Annotated[int, Path(description="Номер авто")]) -> Response:
    async with db.session_factory() as session:
        removed = await services.delete_car(session, car_id)
        await session.commit()
    logger.info("Видалено авто id=%s разом з %s операціями", car_id, removed)
    return Response(status_code=204)
