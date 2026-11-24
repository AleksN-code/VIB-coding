"""Доходи, валюта й дата операції.

- categories.type: 'expense' (витрата) або 'income' (дохід) + категорія доходу «Продаж авто»;
- transactions.operation_date: коли операція відбулася (а created_at — коли її записали);
- transactions.currency: у якій валюті ввели суму — 'UAH' або 'USD';
- transactions.usd_rate: офіційний курс НБУ (грн за $1) на дату операції, фіксується назавжди;
- transactions.amount_uah, amount_usd: сума в обох валютах за цим курсом.

Наявні операції: валюта — гривня, дата операції — дата запису за київським часом,
курс — НБУ на цю дату (береться з сайту НБУ під час міграції).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24
"""

import json
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SALE_CATEGORY = "Продаж авто"


def nbu_usd_rate(day) -> Decimal:
    # Копія логіки з app/nbu.py: міграція не має залежати від коду застосунку,
    # який у майбутньому може змінитися.
    url = (
        "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
        f"?valcode=USD&date={day:%Y%m%d}&json"
    )
    with urllib.request.urlopen(url, timeout=15) as response:
        data = json.load(response)
    if not data:
        raise RuntimeError(f"НБУ не повернув курс на {day:%d.%m.%Y}")
    return Decimal(str(data[0]["rate"]))


def upgrade() -> None:
    conn = op.get_bind()

    # --- categories.type ---
    op.add_column(
        "categories",
        sa.Column("type", sa.String(10), nullable=False, server_default="expense"),
    )
    op.create_check_constraint("ck_categories_type", "categories", "type in ('income', 'expense')")
    conn.execute(
        sa.text(
            "insert into categories (name, type) values (:name, 'income') "
            "on conflict (name) do nothing"
        ),
        {"name": SALE_CATEGORY},
    )

    # --- нові колонки transactions: спершу необов'язкові, щоб заповнити наявні рядки ---
    op.add_column("transactions", sa.Column("operation_date", sa.Date()))
    op.add_column("transactions", sa.Column("currency", sa.String(3)))
    op.add_column("transactions", sa.Column("usd_rate", sa.Numeric(10, 4)))
    op.add_column("transactions", sa.Column("amount_uah", sa.Numeric(14, 2)))
    op.add_column("transactions", sa.Column("amount_usd", sa.Numeric(14, 2)))

    # Наявні операції були введені в гривнях
    conn.execute(
        sa.text(
            "update transactions set "
            "operation_date = (created_at at time zone 'Europe/Kyiv')::date, "
            "currency = 'UAH', amount_uah = amount"
        )
    )
    days = conn.execute(sa.text("select distinct operation_date from transactions")).scalars().all()
    for day in days:
        rate = nbu_usd_rate(day)
        rows = conn.execute(
            sa.text("select id, amount from transactions where operation_date = :day"), {"day": day}
        ).all()
        for row_id, amount in rows:
            usd = (Decimal(amount) / rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
            conn.execute(
                sa.text("update transactions set usd_rate = :rate, amount_usd = :usd where id = :id"),
                {"rate": rate, "usd": usd, "id": row_id},
            )

    # Тепер усі рядки заповнені — робимо колонки обов'язковими
    for column in ("operation_date", "currency", "usd_rate", "amount_uah", "amount_usd"):
        op.alter_column("transactions", column, nullable=False)

    op.create_check_constraint("ck_transactions_currency", "transactions", "currency in ('UAH', 'USD')")
    op.create_check_constraint("ck_transactions_usd_rate_positive", "transactions", "usd_rate > 0")
    op.create_index("ix_transactions_operation_date", "transactions", ["operation_date"])


def downgrade() -> None:
    op.drop_index("ix_transactions_operation_date", table_name="transactions")
    op.drop_constraint("ck_transactions_usd_rate_positive", "transactions", type_="check")
    op.drop_constraint("ck_transactions_currency", "transactions", type_="check")
    for column in ("amount_usd", "amount_uah", "usd_rate", "currency", "operation_date"):
        op.drop_column("transactions", column)

    # Категорію доходу видаляємо, лише якщо на неї немає операцій
    op.execute(
        "delete from categories c where c.type = 'income' "
        "and not exists (select 1 from transactions t where t.category_id = c.id)"
    )
    op.drop_constraint("ck_categories_type", "categories", type_="check")
    op.drop_column("categories", "type")
