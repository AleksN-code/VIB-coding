"""Початкова схема: users, cars, categories, transactions + 6 категорій витрат.

Така база була створена ботом до появи Alembic. Для тієї бази міграцію
не виконують, а лише позначають як виконану: `alembic stamp 0001`.
Для нової порожньої бази (наприклад, на Render) вона створює все з нуля.

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_CATEGORIES = ["Купівля авто", "Доставка", "Розмитнення", "Ремонт", "Запчастини", "Інше"]


def upgrade() -> None:
    categories = op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "cars",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("brand", sa.String(50), nullable=False),
        sa.Column("model", sa.String(50), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("vin", sa.String(17), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("car_id", sa.BigInteger(), sa.ForeignKey("cars.id")),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
    )
    op.create_index("ix_transactions_user_created", "transactions", ["user_id", "created_at"])

    op.bulk_insert(categories, [{"name": name} for name in DEFAULT_CATEGORIES])


def downgrade() -> None:
    op.drop_index("ix_transactions_user_created", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("cars")
    op.drop_table("users")
    op.drop_table("categories")
