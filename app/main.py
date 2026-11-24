"""Telegram-бот на aiogram 3: облік витрат і продажу авто."""

import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, CallbackQuery, Message, User as TgUser
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv
from sqlalchemy.exc import IntegrityError

from app import crud, db, nbu
from app.crud import CarSummary
from app.models import EXPENSE, SALE_CATEGORY, Car

# Читає змінні з файлу .env (якщо він є) у змінні середовища.
# У Docker файлу .env немає — там змінні передає docker-compose.
load_dotenv()

logger = logging.getLogger(__name__)

dp = Dispatcher()

# Дати операцій — за київським часом (контейнер працює в UTC)
KYIV_TZ = ZoneInfo("Europe/Kyiv")


def kyiv_today() -> date:
    return datetime.now(KYIV_TZ).date()


# ---------- Меню й тексти ----------

# Кнопки головного меню (внизу екрана замість клавіатури)
BTN_ADD_CAR = "🚗 Додати авто"
BTN_CARS = "📋 Мої авто"
BTN_EXPENSE = "💸 Додати витрату"
BTN_SALE = "💰 Продаж авто"
BTN_HELP = "❓ Допомога"
MENU_BUTTONS = [BTN_ADD_CAR, BTN_CARS, BTN_EXPENSE, BTN_SALE, BTN_HELP]


def main_menu():
    keyboard = ReplyKeyboardBuilder()
    for text in MENU_BUTTONS:
        keyboard.button(text=text)
    keyboard.adjust(2, 2, 1)
    return keyboard.as_markup(
        resize_keyboard=True,  # компактні кнопки, а не на пів екрана
        is_persistent=True,  # меню не ховається після натискання
        input_field_placeholder="Оберіть дію в меню",
    )


# Команди для кнопки «Меню» в Telegram (біля поля вводу)
BOT_COMMANDS = [
    BotCommand(command="start", description="Головне меню"),
    BotCommand(command="addcar", description="Додати авто"),
    BotCommand(command="cars", description="Мої авто"),
    BotCommand(command="expense", description="Додати витрату"),
    BotCommand(command="sell", description="Продаж авто"),
    BotCommand(command="cancel", description="Скасувати поточну дію"),
    BotCommand(command="help", description="Допомога"),
]

COMMANDS_TEXT = (
    "Користуйтеся кнопками внизу екрана:\n"
    f"{BTN_ADD_CAR} — нове авто\n"
    f"{BTN_EXPENSE} — витрата на авто\n"
    f"{BTN_SALE} — дохід від продажу\n"
    f"{BTN_CARS} — витрати, продаж і прибуток по кожному авто\n"
    f"{BTN_HELP}\n\n"
    "Скасувати будь-яку дію — /cancel"
)

AMOUNT_HELP = (
    "Не вдалося розпізнати суму. Напишіть число без пробілів, "
    "за потреби — з копійками, і опис через пробіл:\n"
    "450 заміна фар\n"
    "1250,50 доставка з Польщі"
)

ADDCAR_HELP = (
    "🚗 Напишіть марку, модель, рік і за бажанням VIN, наприклад:\n"
    "BMW X5 2018\n"
    "Audi A6 Avant 2019 WAUZZZ4G0KN012345\n\n"
    "Марка — одне слово (якщо з двох — через дефіс: Land-Rover).\n"
    "Скасувати — /cancel"
)

DATE_HELP = "✏️ Напишіть дату у форматі ДД.ММ.РРРР, наприклад 18.11.2026"

CATEGORY_ICONS = {
    "Купівля авто": "🛒",
    "Доставка": "🚚",
    "Розмитнення": "🛃",
    "Ремонт": "🔧",
    "Запчастини": "⚙️",
    "Інше": "📦",
    SALE_CATEGORY: "💰",
}

CURRENCY_BUTTONS = {"UAH": "₴ Гривня", "USD": "$ Долар"}
CURRENCY_IN = {"UAH": "у гривнях", "USD": "у доларах"}

# Вид операції в одному спільному сценарії
KIND_EXPENSE = "expense"
KIND_SALE = "sale"

# VIN: 17 символів, латиниця й цифри, без I, O, Q
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
# Сума: ціле число або з 1–2 знаками після крапки чи коми, до 10 цифр перед ними
AMOUNT_RE = re.compile(r"^\d{1,10}([.,]\d{1,2})?$")
# Дата: 25.11.2026 (також 25-11-2026, 25/11/2026)
DATE_RE = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")


class AddCarForm(StatesGroup):
    """Додавання авто: бот чекає повідомлення з даними авто."""

    entering_car = State()


class OperationForm(StatesGroup):
    """Кроки запису операції.

    Витрата: авто → категорія → дата → валюта → сума.
    Продаж:  авто → дата → валюта → сума.
    """

    choosing_car = State()
    choosing_category = State()
    choosing_date = State()
    entering_date = State()
    choosing_currency = State()
    entering_amount = State()


# ---------- Форматування ----------


def format_money(amount: Decimal) -> str:
    """Сума для показу — до цілого числа: 1234.5 → '1 235'.

    У базі суми зберігаються з копійками; округлюємо лише те, що бачить користувач.
    """
    whole = amount.quantize(Decimal("1"), ROUND_HALF_UP)
    return f"{whole:,}".replace(",", " ")


def format_rate(rate: Decimal) -> str:
    """Курс для показу — 2 знаки після коми: 45.0811 → '45.08'. У базі — 4 знаки, як у НБУ."""
    return str(rate.quantize(Decimal("0.01"), ROUND_HALF_UP))


def uah_usd(uah: Decimal, usd: Decimal) -> str:
    return f"{format_money(uah)} грн (${format_money(usd)})"


def signed_uah_usd(uah: Decimal, usd: Decimal) -> str:
    """Прибуток зі знаком: +351 000 грн (+$7 934)."""

    def sign(value: Decimal) -> str:
        return "+" if value > 0 else "−" if value < 0 else ""

    return f"{sign(uah)}{format_money(abs(uah))} грн ({sign(usd)}${format_money(abs(usd))})"


def car_title(car: Car) -> str:
    return f"{car.brand} {car.model} {car.year}"


def category_label(name: str) -> str:
    return f"{CATEGORY_ICONS.get(name, '•')} {name}"


def car_card(car: Car, summary: CarSummary) -> str:
    """Картка авто для «Мої авто»."""
    lines = [f"🚗 {car_title(car)}"]
    if car.vin:
        lines.append(f"🔖 VIN: {car.vin}")
    if summary.sold:
        lines.append(f"✅ Продано {summary.sale_date:%d.%m.%Y}")
    else:
        lines.append("🛠 В роботі")
    lines.append(f"💸 Витрати: {uah_usd(summary.expenses_uah, summary.expenses_usd)}")
    if summary.sold:
        lines.append(f"💰 Продаж: {uah_usd(summary.income_uah, summary.income_usd)}")
        icon, word = ("📈", "Прибуток") if summary.profit_uah >= 0 else ("📉", "Збиток")
        lines.append(f"{icon} {word}: {signed_uah_usd(summary.profit_uah, summary.profit_usd)}")
    return "\n".join(lines)


# ---------- Розбір введеного тексту ----------


def parse_car(args: str | None) -> tuple[str, str, int, str | None] | str:
    """Розбирає 'BMW X5 2018 [VIN]'. Повертає дані авто або текст помилки."""
    parts = (args or "").split()
    # Рік — перше чотиризначне число після марки й хоча б одного слова моделі
    year_index = next(
        (i for i, part in enumerate(parts) if i >= 2 and part.isdigit() and len(part) == 4),
        None,
    )
    if year_index is None or len(parts) > year_index + 2:
        return ADDCAR_HELP

    brand = parts[0]
    model = " ".join(parts[1:year_index])
    year = int(parts[year_index])
    vin = parts[year_index + 1].upper() if len(parts) > year_index + 1 else None

    if len(brand) > 50 or len(model) > 50:
        return "Марка й модель — до 50 символів кожна."
    if not 1950 <= year <= kyiv_today().year + 1:
        return f"Рік {year} виглядає неправильно. Вкажіть рік випуску, напр. 2018."
    if vin is not None and not VIN_RE.match(vin):
        return "VIN має містити 17 символів: латинські літери (без I, O, Q) і цифри."
    return brand, model, year, vin


def parse_amount(text: str) -> tuple[Decimal, str | None] | str:
    """Розбирає '450 заміна фар' або '1250,50'. Повертає (сума, опис) або текст помилки."""
    parts = text.strip().split(maxsplit=1)
    if not parts or not AMOUNT_RE.match(parts[0]):
        return AMOUNT_HELP
    description = parts[1].strip() if len(parts) > 1 else None

    # '1 200 ремонт' — схоже на суму з пробілом між тисячами, а не 1 і опис '200 ремонт'
    if description and re.match(r"^\d{3}\b", description):
        return "Схоже, сума написана з пробілом. Напишіть її разом: 1200 ремонт"

    amount = Decimal(parts[0].replace(",", "."))
    if amount <= 0:
        return "Сума має бути більшою за 0."
    return amount, description


def parse_date(text: str) -> date | str:
    """Розбирає '25.11.2026'. Повертає дату або текст помилки."""
    match = DATE_RE.match(text.strip())
    if not match:
        return DATE_HELP
    try:
        day = date(int(match[3]), int(match[2]), int(match[1]))
    except ValueError:
        return f"Такої дати не існує. {DATE_HELP}"
    if day > kyiv_today():
        return "Дата не може бути в майбутньому: на неї ще немає курсу НБУ."
    if day < date(2000, 1, 1):
        return "Дата занадто давня. Вкажіть дату після 01.01.2000."
    return day


# ---------- Клавіатури кроків ----------


def cancel_keyboard() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✖ Скасувати", callback_data="op_cancel")
    return keyboard


def date_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📅 Сьогодні", callback_data="op_date:today")
    keyboard.button(text="📅 Вчора", callback_data="op_date:yesterday")
    keyboard.button(text="✏️ Інша дата", callback_data="op_date:other")
    keyboard.button(text="✖ Скасувати", callback_data="op_cancel")
    keyboard.adjust(2, 1, 1)
    return keyboard.as_markup()


def currency_keyboard():
    keyboard = InlineKeyboardBuilder()
    for code, text in CURRENCY_BUTTONS.items():
        keyboard.button(text=text, callback_data=f"op_cur:{code}")
    keyboard.button(text="✖ Скасувати", callback_data="op_cancel")
    keyboard.adjust(2, 1)
    return keyboard.as_markup()


def operation_header(data: dict) -> str:
    """Що вже обрано на попередніх кроках — показуємо над кожним наступним кроком."""
    title = "💸 Нова витрата" if data["kind"] == KIND_EXPENSE else "💰 Продаж авто"
    lines = [title, ""]
    if "car_title" in data:
        lines.append(f"🚗 {data['car_title']}")
    if "category_name" in data:
        lines.append(category_label(data["category_name"]))
    if "op_date" in data:
        lines.append(f"📅 {date.fromisoformat(data['op_date']):%d.%m.%Y}")
    if "currency" in data:
        lines.append(CURRENCY_BUTTONS[data["currency"]])
    return "\n".join(lines)


async def get_db_user(session, tg_user: TgUser):
    return await crud.get_or_create_user(
        session, tg_user.id, tg_user.username, tg_user.first_name
    )


# ---------- Загальні команди ----------


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info("Команда /start від user_id=%s", message.from_user.id if message.from_user else None)
    await state.clear()
    await message.answer(
        f"👋 Привіт! Я рахую витрати, продаж і прибуток по кожному авто.\n\n{COMMANDS_TEXT}",
        reply_markup=main_menu(),
    )


@dp.message(Command("help"))
@dp.message(F.text == BTN_HELP)
async def cmd_help(message: Message, state: FSMContext) -> None:
    logger.info("Команда /help від user_id=%s", message.from_user.id if message.from_user else None)
    await state.clear()
    await message.answer(
        "❓ Як користуватися\n\n"
        f"1. {BTN_ADD_CAR} — марка, модель, рік.\n"
        f"2. {BTN_EXPENSE} — авто → категорія → дата → валюта → сума й опис.\n"
        f"3. {BTN_SALE} — авто → дата продажу → валюта → сума.\n"
        f"4. {BTN_CARS} — витрати, продаж і прибуток по кожному авто.\n\n"
        "Суму можна вводити в гривнях або доларах — друга валюта рахується "
        "за офіційним курсом НБУ на дату операції.\n\n"
        "Скасувати будь-яку дію — /cancel",
        reply_markup=main_menu(),
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Нічого скасовувати.")
        return
    await state.clear()
    await message.answer("✖ Скасовано.")


# ---------- Авто ----------


@dp.message(Command("addcar"))
@dp.message(F.text == BTN_ADD_CAR)
async def cmd_addcar(
    message: Message, state: FSMContext, command: CommandObject | None = None
) -> None:
    await state.clear()
    if command is None or not command.args:
        # Кнопка або команда без даних — дані авто чекаємо наступним повідомленням
        await state.set_state(AddCarForm.entering_car)
        await message.answer(ADDCAR_HELP)
        return
    await save_car(message, command.args, state)


# Текст із кнопок меню — не дані авто: його обробляють обробники кнопок
@dp.message(AddCarForm.entering_car, F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_BUTTONS))
async def addcar_enter_data(message: Message, state: FSMContext) -> None:
    await save_car(message, message.text, state)


async def save_car(message: Message, text: str, state: FSMContext) -> None:
    """Розбирає дані авто й зберігає його. При помилці лишає користувача на цьому кроці."""
    parsed = parse_car(text)
    if isinstance(parsed, str):
        await state.set_state(AddCarForm.entering_car)
        await message.answer(parsed if parsed != ADDCAR_HELP else "Не вдалося розібрати.\n\n" + ADDCAR_HELP)
        return
    brand, model, year, vin = parsed

    async with db.session_factory() as session:
        user = await get_db_user(session, message.from_user)
        try:
            car = await crud.add_car(session, user.id, brand, model, year, vin)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            await state.set_state(AddCarForm.entering_car)
            await message.answer(f"Авто з VIN {vin} уже є в базі. Перевірте VIN або /cancel")
            return

    await state.clear()
    logger.info("Додано авто car_id=%s від user_id=%s", car.id, message.from_user.id)
    await message.answer(
        f"✅ Авто додано\n\n🚗 {car_title(car)}"
        + (f"\n🔖 VIN: {car.vin}" if car.vin else "")
        + f"\n\nТепер можна записувати витрати: {BTN_EXPENSE}"
    )


@dp.message(Command("cars"))
@dp.message(F.text == BTN_CARS)
async def cmd_cars(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with db.session_factory() as session:
        user = await get_db_user(session, message.from_user)
        cars = await crud.list_cars(session, user.id)
        summaries = [await crud.car_summary(session, car.id) for car in cars]
        await session.commit()

    if not cars:
        await message.answer(f"У вас ще немає авто. Додати — {BTN_ADD_CAR}")
        return

    cards = [car_card(car, summary) for car, summary in zip(cars, summaries)]
    await message.answer("📋 Ваші авто\n\n" + "\n\n".join(cards))


# ---------- Запис операції: витрата або продаж ----------


@dp.message(Command("expense"))
@dp.message(F.text == BTN_EXPENSE)
async def cmd_expense(message: Message, state: FSMContext) -> None:
    await start_operation(message, state, KIND_EXPENSE)


@dp.message(Command("sell"))
@dp.message(F.text == BTN_SALE)
async def cmd_sell(message: Message, state: FSMContext) -> None:
    await start_operation(message, state, KIND_SALE)


async def start_operation(message: Message, state: FSMContext, kind: str) -> None:
    """Крок 1: вибір авто."""
    await state.clear()
    async with db.session_factory() as session:
        user = await get_db_user(session, message.from_user)
        cars = await crud.list_cars(session, user.id)
        summaries = [await crud.car_summary(session, car.id) for car in cars]
        await session.commit()

    if not cars:
        await state.set_state(AddCarForm.entering_car)
        await message.answer(f"Спершу додайте авто.\n\n{ADDCAR_HELP}")
        return

    keyboard = InlineKeyboardBuilder()
    for car, summary in zip(cars, summaries):
        if kind == KIND_SALE and summary.sold:
            continue  # продане авто вдруге не продаємо
        label = f"🚗 {car_title(car)}" + (" · ✅ продано" if summary.sold else "")
        keyboard.button(text=label, callback_data=f"op_car:{car.id}")
    if kind == KIND_SALE and all(summary.sold for summary in summaries):
        await message.answer(f"✅ Усі ваші авто вже продані. Нове авто — {BTN_ADD_CAR}")
        return
    keyboard.button(text="✖ Скасувати", callback_data="op_cancel")
    keyboard.adjust(1)

    await state.set_state(OperationForm.choosing_car)
    await state.update_data(kind=kind)
    question = "Оберіть авто:" if kind == KIND_EXPENSE else "Яке авто продано?"
    await message.answer(
        f"{operation_header({'kind': kind})}\n\n{question}", reply_markup=keyboard.as_markup()
    )


@dp.callback_query(F.data == "op_cancel")
async def operation_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("✖ Скасовано.")
    await callback.answer()


@dp.callback_query(OperationForm.choosing_car, F.data.startswith("op_car:"))
async def operation_choose_car(callback: CallbackQuery, state: FSMContext) -> None:
    """Крок 2: категорія (для витрати) або одразу дата (для продажу)."""
    car_id = int(callback.data.split(":", 1)[1])
    data = await state.get_data()

    async with db.session_factory() as session:
        user = await get_db_user(session, callback.from_user)
        # Перевіряємо, що авто належить саме цьому користувачу
        car = await crud.get_user_car(session, user.id, car_id)
        summary = await crud.car_summary(session, car_id) if car else None
        categories = await crud.list_categories(session, EXPENSE)
        await session.commit()

    if car is None:
        await state.clear()
        await callback.message.edit_text("Авто не знайдено. Почніть заново.")
        await callback.answer()
        return
    if data["kind"] == KIND_SALE and summary.sold:
        await callback.answer("Це авто вже продано", show_alert=True)
        return

    await state.update_data(car_id=car.id, car_title=car_title(car))
    data = await state.get_data()

    if data["kind"] == KIND_EXPENSE:
        keyboard = InlineKeyboardBuilder()
        for category in categories:
            keyboard.button(text=category_label(category.name), callback_data=f"op_cat:{category.id}")
        keyboard.button(text="✖ Скасувати", callback_data="op_cancel")
        keyboard.adjust(2)
        await state.set_state(OperationForm.choosing_category)
        await callback.message.edit_text(
            f"{operation_header(data)}\n\nОберіть категорію:", reply_markup=keyboard.as_markup()
        )
    else:
        await state.set_state(OperationForm.choosing_date)
        await callback.message.edit_text(
            f"{operation_header(data)}\n\nДата продажу:", reply_markup=date_keyboard()
        )
    await callback.answer()


@dp.callback_query(OperationForm.choosing_category, F.data.startswith("op_cat:"))
async def operation_choose_category(callback: CallbackQuery, state: FSMContext) -> None:
    """Крок 3 (витрата): дата."""
    category_id = int(callback.data.split(":", 1)[1])
    async with db.session_factory() as session:
        category = await crud.get_category(session, category_id)

    if category is None or category.type != EXPENSE:
        await callback.answer("Категорію не знайдено", show_alert=True)
        return

    await state.update_data(category_id=category.id, category_name=category.name)
    await state.set_state(OperationForm.choosing_date)
    data = await state.get_data()
    await callback.message.edit_text(
        f"{operation_header(data)}\n\nДата витрати:", reply_markup=date_keyboard()
    )
    await callback.answer()


@dp.callback_query(OperationForm.choosing_date, F.data.startswith("op_date:"))
async def operation_choose_date(callback: CallbackQuery, state: FSMContext) -> None:
    choice = callback.data.split(":", 1)[1]
    if choice == "other":
        await state.set_state(OperationForm.entering_date)
        data = await state.get_data()
        await callback.message.edit_text(
            f"{operation_header(data)}\n\n{DATE_HELP}", reply_markup=cancel_keyboard().as_markup()
        )
        await callback.answer()
        return

    day = kyiv_today() if choice == "today" else kyiv_today() - timedelta(days=1)
    await state.update_data(op_date=day.isoformat())
    await state.set_state(OperationForm.choosing_currency)
    data = await state.get_data()
    await callback.message.edit_text(
        f"{operation_header(data)}\n\nУ якій валюті сума?", reply_markup=currency_keyboard()
    )
    await callback.answer()


@dp.message(OperationForm.entering_date, F.text, ~F.text.in_(MENU_BUTTONS))
async def operation_enter_date(message: Message, state: FSMContext) -> None:
    parsed = parse_date(message.text)
    if isinstance(parsed, str):
        await message.answer(parsed, reply_markup=cancel_keyboard().as_markup())
        return

    await state.update_data(op_date=parsed.isoformat())
    await state.set_state(OperationForm.choosing_currency)
    data = await state.get_data()
    await message.answer(
        f"{operation_header(data)}\n\nУ якій валюті сума?", reply_markup=currency_keyboard()
    )


@dp.callback_query(OperationForm.choosing_currency, F.data.startswith("op_cur:"))
async def operation_choose_currency(callback: CallbackQuery, state: FSMContext) -> None:
    currency = callback.data.split(":", 1)[1]
    if currency not in CURRENCY_BUTTONS:
        await callback.answer("Невідома валюта", show_alert=True)
        return

    await state.update_data(currency=currency)
    await state.set_state(OperationForm.entering_amount)
    data = await state.get_data()
    example = "450 заміна фар" if data["kind"] == KIND_EXPENSE else "1500000 продаж через OLX"
    if currency == "USD":
        example = "300 заміна фар" if data["kind"] == KIND_EXPENSE else "35000 продаж через OLX"
    await callback.message.edit_text(
        f"{operation_header(data)}\n\n"
        f"💵 Надішліть суму {CURRENCY_IN[currency]} і за бажанням опис, наприклад:\n{example}",
        reply_markup=cancel_keyboard().as_markup(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith(("op_", "exp_")))
async def operation_outdated_button(callback: CallbackQuery) -> None:
    """Кнопка зі старого повідомлення (наприклад, після перезапуску бота або іншого кроку)."""
    await callback.answer("Ця кнопка вже не діє. Почніть заново з меню.", show_alert=True)


@dp.message(OperationForm.entering_amount, F.text, ~F.text.in_(MENU_BUTTONS))
async def operation_enter_amount(message: Message, state: FSMContext) -> None:
    """Останній крок: сума й опис → курс НБУ → запис у базу."""
    parsed = parse_amount(message.text)
    if isinstance(parsed, str):
        await message.answer(parsed, reply_markup=cancel_keyboard().as_markup())
        return
    amount, description = parsed

    data = await state.get_data()
    kind = data["kind"]
    operation_date = date.fromisoformat(data["op_date"])
    currency = data["currency"]

    try:
        usd_rate = await asyncio.to_thread(nbu.get_usd_rate, operation_date)
    except nbu.NbuRateError as error:
        logger.warning("Курс НБУ недоступний: %s", error)
        await message.answer(
            "⚠️ Не вдалося отримати офіційний курс долара НБУ, тому операцію не записано.\n"
            "Надішліть суму ще раз за хвилину або скасуйте — /cancel"
        )
        return

    async with db.session_factory() as session:
        user = await get_db_user(session, message.from_user)
        # lock=True: поки записуємо, інший продаж цього авто чекає
        car = await crud.get_user_car(session, user.id, data["car_id"], lock=True)
        if car is None:
            await state.clear()
            await message.answer("Авто не знайдено. Почніть заново.")
            return

        if kind == KIND_SALE:
            if (await crud.car_summary(session, car.id)).sold:
                await state.clear()
                await message.answer("✅ Це авто вже продано — другий продаж не записано.")
                return
            category = await crud.get_category_by_name(session, SALE_CATEGORY)
            category_id, category_name = category.id, category.name
        else:
            category_id, category_name = data["category_id"], data["category_name"]

        transaction = await crud.add_transaction(
            session, user.id, car.id, category_id,
            operation_date, amount, currency, usd_rate, description,
        )
        summary = await crud.car_summary(session, car.id)
        await session.commit()

    await state.clear()
    logger.info(
        "Записано операцію kind=%s transaction_id=%s car_id=%s від user_id=%s",
        kind, transaction.id, car.id, message.from_user.id,
    )

    # Спершу — у валюті, в якій ввели суму
    if currency == "USD":
        amount_text = f"${format_money(transaction.amount_usd)} ({format_money(transaction.amount_uah)} грн)"
    else:
        amount_text = uah_usd(transaction.amount_uah, transaction.amount_usd)

    lines = [
        "✅ Витрату записано" if kind == KIND_EXPENSE else "✅ Продаж записано",
        "",
        f"🚗 {car_title(car)}",
        category_label(category_name),
        f"📅 {operation_date:%d.%m.%Y}",
        f"💵 {amount_text} · курс НБУ {format_rate(usd_rate)}",
    ]
    if description:
        lines.append(f"📝 {description}")
    lines += ["", "📊 Підсумок по авто", car_card(car, summary).split("\n", 1)[1]]
    await message.answer("\n".join(lines))


@dp.message()
async def unknown_message(message: Message) -> None:
    """Усе, що не підійшло жодному обробнику вище: бот не мовчить, а підказує."""
    await message.answer(f"🤔 Не зрозумів повідомлення.\n\n{COMMANDS_TEXT}", reply_markup=main_menu())


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("Не задано BOT_TOKEN — бот не може запуститися")
        raise SystemExit("Не задано BOT_TOKEN. Додайте його у файл .env (див. .env.example).")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("Не задано DATABASE_URL — бот не може підключитися до бази")
        raise SystemExit("Не задано DATABASE_URL. Додайте його у файл .env (див. .env.example).")

    db.setup_engine(database_url)
    await db.check_db()

    bot = Bot(token=token)
    # Список команд для кнопки «Меню» біля поля вводу в Telegram
    await bot.set_my_commands(BOT_COMMANDS)
    logger.info("Бот запускається")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close_db()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
