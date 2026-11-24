"""Офіційний курс долара НБУ і перерахунок сум між гривнею та доларом.

API НБУ: https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode=USD&date=YYYYMMDD&json
Відкрите, безкоштовне, без ключа. Курс є на кожен день (і на вихідні),
для майбутніх дат — порожня відповідь.
"""

import json
import urllib.error
import urllib.request
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

NBU_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
CENT = Decimal("0.01")


class NbuRateError(Exception):
    """Курс НБУ отримати не вдалося — операцію з неправильним курсом не записуємо."""


@lru_cache(maxsize=512)
def get_usd_rate(on: date) -> Decimal:
    """Скільки гривень коштує 1 долар за офіційним курсом НБУ на дату `on`.

    Курс на минулу дату не змінюється, тому результат кешується в пам'яті.
    """
    url = f"{NBU_URL}?valcode=USD&date={on:%Y%m%d}&json"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise NbuRateError(f"сайт НБУ недоступний: {error}") from error

    if not data:
        raise NbuRateError(f"НБУ ще не встановив курс на {on:%d.%m.%Y}")
    return Decimal(str(data[0]["rate"]))


def to_uah_usd(amount: Decimal, currency: str, usd_rate: Decimal) -> tuple[Decimal, Decimal]:
    """Сума в гривнях і доларах. `currency` — валюта, в якій суму ввели: 'UAH' або 'USD'."""
    if currency == "UAH":
        uah = amount
        usd = (amount / usd_rate).quantize(CENT, ROUND_HALF_UP)
    elif currency == "USD":
        usd = amount
        uah = (amount * usd_rate).quantize(CENT, ROUND_HALF_UP)
    else:
        raise ValueError(f"Невідома валюта: {currency}")
    return uah, usd
