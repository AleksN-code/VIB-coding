"""Підключення до бази Neon PostgreSQL через SQLAlchemy."""

import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.models import DEFAULT_CATEGORIES, Base, Category

logger = logging.getLogger(__name__)

engine: AsyncEngine | None = None
# Фабрика сесій: кожен запис у базу робимо в окремій сесії
session_factory: async_sessionmaker | None = None


def setup_engine(database_url: str) -> None:
    """Створює підключення до бази. Сам рядок підключення в лог не пишемо — у ньому пароль."""
    global engine, session_factory

    # Neon дає рядок postgresql://..., а SQLAlchemy треба вказати драйвер psycopg
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_async_engine(
        database_url,
        # Neon pooler (PgBouncer) не підтримує кешування підготовлених запитів psycopg
        connect_args={"prepare_threshold": None},
        # Neon «засинає» без навантаження — перевіряємо з'єднання перед використанням
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Створює таблиці, яких ще немає, і додає стандартні категорії."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Додаємо категорії; ті, що вже є, пропускаємо
        await conn.execute(
            insert(Category)
            .values([{"name": name} for name in DEFAULT_CATEGORIES])
            .on_conflict_do_nothing(index_elements=["name"])
        )

    logger.info("База даних готова: таблиці створені, категорій — %d", len(DEFAULT_CATEGORIES))


async def close_db() -> None:
    """Закриває всі з'єднання з базою."""
    if engine is not None:
        await engine.dispose()
