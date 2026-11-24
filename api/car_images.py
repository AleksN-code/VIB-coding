"""Картинка моделі авто з Вікіпедії — для вкладки авто в адмінці.

Це загальне фото моделі (не конкретного авто користувача, покоління може не збігатися).
Пізніше його замінить фото, надіслане в бота.

Безкоштовний відкритий API Вікіпедії, без ключа. Передаємо лише марку й модель.
"""

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger("api.car_images")

SEARCH_URL = "https://en.wikipedia.org/w/api.php"
# Вікіпедія просить автоматичних клієнтів називати себе в User-Agent
HEADERS = {"User-Agent": "CarFinanceAdmin/0.1 (learning project)"}


@dataclass(frozen=True)
class CarImage:
    url: str  # саме зображення
    page_title: str  # сторінка Вікіпедії, звідки воно (для підпису й ліцензії)
    page_url: str


@lru_cache(maxsize=256)
def find_car_image(brand: str, model: str) -> CarImage | None:
    """Шукає статтю про модель і бере її головне зображення. Кешується на час роботи API."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{brand} {model} car",
        "gsrlimit": 1,
        "prop": "pageimages",
        "piprop": "thumbnail",
        "pithumbsize": 640,
    }
    request = urllib.request.Request(f"{SEARCH_URL}?{urllib.parse.urlencode(params)}", headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.load(response)
    except Exception as error:  # Вікіпедія недоступна — просто без картинки
        logger.warning("Вікіпедія недоступна для %s %s: %s", brand, model, type(error).__name__)
        return None

    pages = list((data.get("query") or {}).get("pages", {}).values())
    if not pages or "thumbnail" not in pages[0]:
        return None
    page = pages[0]

    # Пошук може повернути щось інше («Test Car» → «Kei car»): беремо картинку,
    # лише якщо в назві статті є і марка, і перше слово моделі
    title = page["title"].lower()
    if brand.lower().replace("-", " ") not in title.replace("-", " ") or model.split()[0].lower() not in title:
        return None

    page_url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page["title"].replace(" ", "_"))
    return CarImage(url=page["thumbnail"]["source"], page_title=page["title"], page_url=page_url)
