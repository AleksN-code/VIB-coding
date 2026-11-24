"""Підключення до бази Neon PostgreSQL через SQLAlchemy.

Таблиці створюють і змінюють міграції Alembic (папка migrations/),
а не код бота: `docker compose up` запускає їх перед стартом бота.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

engine: AsyncEngine | None = None
# Фабрика сесій: кожна дія з базою — в окремій сесії
session_factory: async_sessionmaker | None = None


def sqlalchemy_url(database_url: str) -> str:
    """Neon дає рядок postgresql://..., а SQLAlchemy треба вказати драйвер psycopg."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def setup_engine(database_url: str) -> None:
    """Створює підключення до бази. Сам рядок підключення в лог не пишемо — у ньому пароль."""
    global engine, session_factory

    engine = create_async_engine(
        sqlalchemy_url(database_url),
        # Neon pooler (PgBouncer) не підтримує кешування підготовлених запитів psycopg
        connect_args={"prepare_threshold": None},
        # Neon «засинає» без навантаження — перевіряємо з'єднання перед використанням
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def check_db() -> None:
    """Перевіряє, що база відповідає і міграції застосовані."""
    async with engine.connect() as conn:
        version = await conn.scalar(text("select version_num from alembic_version"))
    logger.info("Підключено до бази, версія схеми (міграція): %s", version)


async def close_db() -> None:
    """Закриває всі з'єднання з базою."""
    if engine is not None:
        await engine.dispose()
