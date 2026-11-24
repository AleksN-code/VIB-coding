"""Правила перевірки даних — спільні для Telegram-бота і web-адмінки.

Тут немає роботи з базою, лише відповідь на питання «чи правильні дані».
Бот і backend API перевіряють введене цими самими функціями,
тому правила в боті й на сайті не можуть розійтися.

Кожна функція повертає очищене значення (без зайвих пробілів, VIN — великими літерами)
або кидає ValidationError з поясненням для людини.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.errors import ValidationError
from app.models import CURRENCIES

# Дати операцій — за київським часом (контейнери працюють в UTC)
KYIV_TZ = ZoneInfo("Europe/Kyiv")

# Курс НБУ беремо з 2000 року — раніші дати для нашого обліку не потрібні
MIN_OPERATION_DATE = date(2000, 1, 1)
MIN_CAR_YEAR = 1950
# Найбільша сума, яка вміщується в колонку amount — Numeric(12, 2)
MAX_AMOUNT = Decimal("9999999999.99")
CENT = Decimal("0.01")
MAX_NAME_LENGTH = 50  # марка й модель — String(50)
MAX_DESCRIPTION_LENGTH = 500

# VIN: 17 символів, латиниця й цифри, без I, O, Q
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def kyiv_today() -> date:
    return datetime.now(KYIV_TZ).date()


def check_amount(amount: Decimal) -> Decimal:
    """Сума: число більше нуля, не більше двох знаків після коми."""
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise ValidationError("Сума має бути числом.")
    if amount <= 0:
        raise ValidationError("Сума має бути більшою за 0.")
    if amount > MAX_AMOUNT:
        raise ValidationError("Сума занадто велика.")
    if amount != amount.quantize(CENT):
        raise ValidationError("У сумі може бути не більше двох знаків після коми.")
    return amount


def check_currency(currency: str) -> str:
    """Валюта, в якій ввели суму: UAH або USD."""
    if currency not in CURRENCIES:
        raise ValidationError("Валюта має бути UAH (гривня) або USD (долар).")
    return currency


def check_operation_date(day: date) -> date:
    """Дата операції: не в майбутньому (на неї ще немає курсу НБУ) і не раніше 2000 року."""
    if day > kyiv_today():
        raise ValidationError("Дата не може бути в майбутньому: на неї ще немає курсу НБУ.")
    if day < MIN_OPERATION_DATE:
        raise ValidationError(f"Дата занадто давня. Вкажіть дату після {MIN_OPERATION_DATE:%d.%m.%Y}.")
    return day


def check_description(description: str | None) -> str | None:
    """Опис необов'язковий: порожній рядок — те саме, що без опису."""
    description = (description or "").strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(f"Опис — до {MAX_DESCRIPTION_LENGTH} символів.")
    return description or None


def check_car(
    brand: str, model: str, year: int, vin: str | None
) -> tuple[str, str, int, str | None]:
    """Дані авто: марка, модель, рік випуску й необов'язковий VIN."""
    brand, model = (brand or "").strip(), (model or "").strip()
    if not brand or not model:
        raise ValidationError("Вкажіть марку й модель авто.")
    if len(brand) > MAX_NAME_LENGTH or len(model) > MAX_NAME_LENGTH:
        raise ValidationError(f"Марка й модель — до {MAX_NAME_LENGTH} символів кожна.")
    if not MIN_CAR_YEAR <= year <= kyiv_today().year + 1:
        raise ValidationError(f"Рік {year} виглядає неправильно. Вкажіть рік випуску, напр. 2018.")

    vin = (vin or "").strip().upper() or None
    if vin is not None and not VIN_RE.match(vin):
        raise ValidationError("VIN має містити 17 символів: латинські літери (без I, O, Q) і цифри.")
    return brand, model, year, vin
